"""Enhance Mode as two tools: send a goal, then ask how the job is doing.

The job runs in a process of its own because the photograph takes minutes. It reads the
game and never writes to it; it writes files in the Enhance folder and spends image
generations from the ChatGPT plan the user's Codex CLI is signed in with.
"""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from . import enhance


def register_enhance_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
    def fm_enhance_goal(
        scorer: Annotated[str | None, Field(min_length=2, max_length=80)] = None,
        match_key: Annotated[int | None, Field(strict=True, gt=0)] = None,
        event_id: Annotated[int | None, Field(strict=True, ge=0)] = None,
        goal_number: Annotated[int | None, Field(strict=True, ge=1, le=30)] = None,
        direction: Annotated[str | None, Field(max_length=600)] = None,
        job_id: Annotated[str | None, Field(min_length=1, max_length=200)] = None,
        from_job_id: Annotated[str | None, Field(min_length=1, max_length=200)] = None,
        wait_seconds: Annotated[float | None, Field(ge=0, le=300)] = None,
        allow_no_replay: Annotated[bool | None, Field(strict=True)] = None,
    ) -> dict[str, Any]:
        """Enhance Mode: turn a goal from the running career into a photorealistic press photograph ("send that Henrique goal to enhance mode"). Give part of the scorer's name, or nothing for the goal the game's match review is showing. The match whose replay is open in the game is used when it has such a goal, otherwise the most recent retained match that does, unless match_key names one. The job watches the replay for wait_seconds (default 20) and reads the goal's frames as they play (player positions and ball around the strike), photographs the game window for the kits, reads the installed face portraits, has the user's own Codex CLI generate the image on their ChatGPT plan, checks every visible player's proportions, likeness, kit and focus, and attaches the photograph only when that review passes. It returns at once with a job_id; poll fm_enhance_status, typically for several minutes. States that need the user: capture_needed (the user plays the goal in Football Manager's match review, then call again with job_id; the game keeps the ball-in-the-net frame of a goal it has shown, and the strike itself is read only while the goal plays during the watch), choose_goal (call again with job_id and an event_id from goal_choices), codex_needed (install Codex or sign it in with ChatGPT), review_failed (call again with job_id for another correction turn). For another photograph of the same goal, such as a different camera, pass from_job_id with a direction: the captured evidence is reused. The image is an AI reconstruction of a game event; direction never moves a player, the ball or a kit. Reads the game only; writes files in the Enhance folder; no API key is used."""
        if job_id:
            folder = enhance.resolve(job_id)
            enhance.update_params(folder, {'event_id': event_id, 'goal_number': goal_number,
                                           'wait_seconds': wait_seconds, 'allow_no_replay': allow_no_replay})
        else:
            folder = enhance.create_job({'scorer': scorer, 'match_key': match_key, 'event_id': event_id,
                                         'goal_number': goal_number, 'direction': direction,
                                         'from_job': from_job_id, 'wait_seconds': wait_seconds,
                                         'allow_no_replay': allow_no_replay})
        if enhance.load(folder)['state'] != 'done':
            enhance.spawn(folder)
        return enhance.status(folder)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_enhance_status(
        job_id: Annotated[str | None, Field(min_length=1, max_length=200)] = None,
    ) -> dict[str, Any]:
        """Report an Enhance Mode job from fm_enhance_goal: its state (running, done, capture_needed, choose_goal, codex_needed, review_failed, failed, interrupted), the stage it is on, what the user has to do next, and when done the paths of the photograph, its gallery page (original replay, positions, provenance) and the recorded review. Without job_id, lists the ten most recent jobs. A done job's image passed a recorded per-player visual review by the generating model; that is a recorded judgement, not proof of likeness or of pixel-exact positions."""
        if job_id:
            return enhance.status(enhance.resolve(job_id))
        return {'jobs': enhance.recent()}

    return ['fm_enhance_goal', 'fm_enhance_status']
