"""Race the real registered tool from an attacker outside its write sandbox."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


root = Path(__file__).resolve().parent.parent
hook = '''
import os
from pathlib import Path
import time
original_open = os.open
triggered = False

def racing_open(path, flags, *args, **kwargs):
    global triggered
    fd = original_open(path, flags, *args, **kwargs)
    if not triggered and Path(path).name == os.environ['RACE_GATE']:
        triggered = True
        Path(os.environ['RACE_READY']).write_text('ready')
        deadline = time.monotonic() + 5
        while not Path(os.environ['RACE_RELEASE']).exists():
            if time.monotonic() > deadline:
                raise RuntimeError('race coordinator did not release the writer')
            time.sleep(0.005)
    return fd
os.open = racing_open
'''

for gate in ('checked', 'report.txt'):
    with tempfile.TemporaryDirectory(dir=root / 'evidence') as scratch, \
            tempfile.TemporaryDirectory(prefix='.fm-text-external-', dir=root.parent) as outside:
        scratch, outside = Path(scratch), Path(outside)
        parent = scratch / 'checked'
        parent.mkdir()
        (scratch / 'sitecustomize.py').write_text(hook)
        ready, release = scratch / 'ready', scratch / 'release'
        params = {'path': str(parent / 'report.txt'), 'content': 'must not be written outside'}
        program = f'''
import {{ registerTextFileTool }} from {json.dumps((root / 'pi/fm-text-files.mjs').as_uri())};
let tool;
registerTextFileTool({{ registerTool(value) {{ tool = value; }} }});
console.log(JSON.stringify(await tool.execute('race', {json.dumps(params)})));
'''
        process = subprocess.Popen([shutil.which('node'), '--input-type=module', '-e', program],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   env={**os.environ, 'PYTHONPATH': str(scratch), 'RACE_GATE': gate,
                                        'RACE_READY': str(ready), 'RACE_RELEASE': str(release)})
        try:
            deadline = time.monotonic() + 8
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.005)
            assert ready.exists(), f'{gate}: writer never reached the race barrier'
            parent.rename(outside / 'moved')
            parent.mkdir()
            release.write_text('continue')
            stdout, stderr = process.communicate(timeout=10)
            assert process.returncode == 0, stderr
            result = json.loads(stdout)
            assert result.get('isError') is True, result
            relocated = outside / 'moved' / 'report.txt'
            if gate == 'checked':
                assert not relocated.exists(), 'must not create a file through a relocated parent'
            # After file open, the other process moved an already-authorized inode.
            # The writer must return an error, not a stale success receipt; the OS
            # cannot revoke the file descriptor merely because its name moved.
            assert not (parent / 'report.txt').exists()
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

print(json.dumps({'checked_relocations': 2}))
