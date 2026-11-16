"""Opening-frontmatter identity controls in an approved synthetic directory."""
import importlib.util
import json
from pathlib import Path
import tempfile

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('guide_reader', root / 'pi/fm-skill-reader.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
cases = json.loads((root / 'tests/skill-identity-cases.json').read_text())
rejected = 0
with tempfile.TemporaryDirectory(dir=root / 'evidence') as scratch:
    approved = Path(scratch)
    (approved / 'fm-tools').mkdir()
    target = approved / 'fm-tools/SKILL.md'
    for fixture in cases:
        assert reader.valid_guide_identity(fixture['content'], 'fm-tools') is fixture['accepted'], fixture['label']
        target.write_text(fixture['content'])
        try:
            result = reader.read_guide(str(approved), 'fm-tools')
        except ValueError:
            assert not fixture['accepted'], fixture['label']
            rejected += 1
        else:
            assert fixture['accepted'] and result['content'] == fixture['content'], fixture['label']
print(json.dumps(dict(controls=len(cases), rejected=rejected)))
