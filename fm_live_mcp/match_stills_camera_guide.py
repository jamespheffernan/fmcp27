"""Composition guide for the chosen camera: a new data diagram, never an edited photograph.

Only XY and ball XYZ are decoded. Stick-figure elevations are labelled artistic
assumptions. Drawing needs matplotlib, which the reader does not depend on:
`render_file` uses it when importable and otherwise asks `uv` for it.
"""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .match_stills_camera import goal_lines, project


def render(scene, destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    camera = scene['camera']
    scorer = scene['goal']['actor']['canonical_person_id']
    fig, ax = plt.subplots(figsize=(12, 8), dpi=128)
    fig.subplots_adjust(0, 0, 1, 1)
    fig.patch.set_facecolor('#c9d6c3')
    ax.set(xlim=(0, 1), ylim=(1, 0))
    ax.set_facecolor('#c9d6c3')
    # The goal, its net and the markings in front of it, so every figure has the pitch to stand on.
    goal = scene['goal']
    sign = 1 if goal['attacked_goal_positive_native_y'] else -1
    extents = scene['replay'].get('retained_pitch_geometry') or {}
    lines = goal_lines(sign, extents['half_length_native'], extents.get('half_width_native') or 34.0)
    for kind, colour, width in (('markings', '#ffffff', 5), ('net', '#9aa3ad', 1.5), ('frame', '#5a6470', 6)):
        for _, a, b in lines[kind]:
            run = []
            for i in range(41):  # sampled, so a line that passes behind the camera is drawn up to where it leaves view
                seen = project([a[k]+(b[k]-a[k])*i/40 for k in range(3)], camera)
                if seen.get('in_front') and all(-1 <= v <= 2 for v in seen['uv']):
                    run.append(seen['uv'])
                elif run:
                    ax.plot(*zip(*run), color=colour, lw=width, solid_capstyle='round', zorder=1); run = []
            if run:
                ax.plot(*zip(*run), color=colour, lw=width, solid_capstyle='round', zorder=1)
    spot = project(lines['penalty_spot'], camera)
    if spot.get('in_front') and spot.get('inside_image'):
        ax.scatter(*spot['uv'], s=60, color='#ffffff', zorder=1)
    post = (camera.get('goal') or {}).get('projected_uv', {}).get('near post top')
    if post and all(0 <= v <= 1 for v in post):
        ax.text(post[0], post[1]-.02, 'GOAL · posts, bar and net', fontsize=10, color='#5a6470', ha='center', zorder=10)
    numbers = {p['canonical_person_id']: p['number'] for p in (scene.get('shirt_numbers') or {}).get('players', [])}
    people = sorted(scene['replay']['players'], reverse=True,
                    key=lambda p: math.dist(p['native_xy'], camera['position_native'][:2]) if p.get('native_xy') else 0)
    for person in people:
        if person.get('native_xy') is None:
            continue
        x, y = person['native_xy']
        # The scorer of a header is lifted only as far as the height the ball was met at requires.
        figure = (scene.get('action_sequence') or {}).get('scorer_figure') if person['canonical_person_id'] == scorer else None
        foot_z, head_z = (figure['foot_z'], figure['head_z']) if figure else (0, 1.8)
        feet = project([x, y, foot_z], camera)
        head = project([x, y, head_z], camera)
        if not feet.get('in_front') or not head.get('inside_image'):
            continue
        fx, fy = feet['uv']; hx, hy = head['uv']
        height = abs(fy-hy)
        if height < .08:
            continue
        colour = '#191c1f' if person['side_index'] == 0 else '#cf2727'
        shoulder, hip = hy+height*.2, hy+height*.6
        ax.plot([hx, hx], [hy, hip], color=colour, lw=max(2, height*30), solid_capstyle='round')
        ax.plot([hx-height*.20, hx, hx+height*.20], [shoulder+height*.1, shoulder, shoulder+height*.1], color=colour, lw=3)
        ax.plot([fx-height*.13, hx, fx+height*.13], [fy, hip, fy], color=colour, lw=3)
        ax.scatter([hx], [hy], s=max(30, height*300), color=colour, edgecolor='white', zorder=4)
        number = numbers.get(person['canonical_person_id'])
        ax.text(hx+.018, hy-.015, person['person_name'] + (f' · {number}' if number else ''), fontsize=9, color=colour,
                bbox={'facecolor':'white', 'alpha':.85, 'edgecolor':'none', 'pad':2}, zorder=5)
    ball = camera.get('projected_ball')
    if ball and ball.get('inside_image'):
        x, y = ball['uv']
        ax.scatter([x], [y], s=160, color='#f7c948', edgecolor='#111', zorder=10)
        ax.text(x+.02, y, 'BALL · decoded XYZ', fontsize=10, zorder=10)
    ax.text(.025, .04, 'CHOSEN CAMERA · ' + camera.get('place', 'low, beside the goal line').upper(), weight='bold', fontsize=14)
    ax.text(.025, .075, 'Player XY + ball XYZ decoded · human Z / pose schematic, not decoded · goal and markings from the Laws of the Game', fontsize=10)
    ax.axis('off')
    fig.savefig(destination)
    plt.close(fig)


def render_file(scene_path: Path, destination: Path) -> str | None:
    """Draw the guide. Returns None on success, otherwise why no guide was drawn."""
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        # A server started by a desktop app has a short PATH; look where uv is usually installed too.
        uv = shutil.which('uv') or next((str(p) for p in (Path.home()/'.local/bin/uv', Path.home()/'.cargo/bin/uv',
                                                             Path('/opt/homebrew/bin/uv'), Path('/usr/local/bin/uv')) if p.is_file()), None)
        if not uv:
            return 'matplotlib is not installed and uv is not available to supply it'
        root = str(Path(__file__).resolve().parents[1])
        done = subprocess.run(
            [uv, 'run', '--no-project', '--with', 'matplotlib', 'python', '-m',
             'fm_live_mcp.match_stills_camera_guide', str(scene_path), str(destination)],
            env={**os.environ, 'PYTHONPATH': root}, cwd=root, capture_output=True, text=True, timeout=300)
        if done.returncode or not destination.is_file():
            return f'uv could not draw the guide: {done.stderr.strip()[-300:]}'
        return None
    render(json.loads(scene_path.read_text()), destination)
    return None


if __name__ == '__main__':
    render(json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2]))
