"""Live-gated differential check: generic reader against the existing tools on a small sample.

Skipped unless a supported FM27 process and the native helper are available. Reads only.

PINNED_FAMILIES and PINNED_FIELDS list what reached 100% agreement (no mismatch among the
records where both readers produced a value) in the committed report `docs/fmdb/ORACLE.md`
(129 players, 50 staff, 51 clubs, 50 competitions, 50 stadiums, 50 cities, 173 currencies).
Those fields must not regress on the small sample used here. A field outside the lists has a
classified mismatch in the report and is not asserted. Regenerate the lists from the report,
never edit them to hide a mismatch.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _live_available():
    if sys.platform != 'darwin':
        return False
    try:
        from fm_live_mcp.bridge import Bridge, discover_processes
        return Bridge().helper.is_file() and len(discover_processes()) == 1
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')

# Families whose every mapped field was at 100% in the 2026-11-11 report (re-run after the gap fixes); PINNED_FIELDS names the
# individual fields at 100% in families that are only partly in agreement.
PINNED_FAMILIES = (
    'player.identity',
    'player.attributes',
    'player.attributes_raw',
    'player.goalkeeping',
    'player.goalkeeping_raw',
    'player.hidden',
    'player.hidden_raw',
    'player.feet',
    'player.feet_raw',
    'player.ability',
    'player.positions',
    'player.personality',
    'player.contract',
    'player.value',
    'player.terms',
    'staff.identity',
    'staff.attributes_raw',
    'staff.tendencies',
    'staff.tendencies_raw',
    'staff.board',
    'staff.board_raw',
    'staff.personality',
    'club.identity',
    'club.finance',
    'club.facilities',
    'competition.identity',
    'competition.context',
    'nation.identity',
    'continent.identity',
    'stadium.identity',
    'stadium.capacity',
    'stadium.links',
    'city.identity',
    'city.links',
)
PINNED_FIELDS = (
    'player.health.match_sharpness',
    'player.health.fatigue',
    'player.health.condition_stored',
    'player.health.injury_list_len',
    'player.health.injury_present',
    'player.health.injury_started',
    'player.health.injury_sentence_name',
    'player.health.injury_name',
    'player.club.on_loan',
    'staff.job.native_code',
    'staff.contract.joined',
    'staff.contract.last_signed',
    'staff.contract.expires',
    'staff.contract.wage_weekly_gbp',
    'staff.contract.status_code',
    'stadium.pitch.latitude',
    'stadium.pitch.longitude',
    'stadium.pitch.type_label',
    'stadium.pitch.condition',
    'stadium.pitch.deterioration_code',
    'stadium.pitch.recovery_rate',
    'stadium.pitch.length_default',
    'stadium.pitch.width_default',
    'stadium.pitch.length_minimum',
    'stadium.pitch.width_maximum',
    'stadium.pitch.width_minimum',
    'stadium.pitch.length_maximum',
    'stadium.pitch.length_international',
    'stadium.pitch.width_international',
    'stadium.pitch.type_code_stored',
    'currency.identity.exchange_rate',
    'currency.identity.name_stored',
)


class Args:
    players = 6
    staff = 6
    clubs = 6
    competitions = 8
    stadiums = 8
    cities = 8
    currencies = 12
    seed = 20261111
    no_managed = False
    managed_limit = 3
    samples = ''


@pytest.fixture(scope='module')
def report():
    sys.path.insert(0, str(ROOT / 'scripts'))
    import fmdb_oracle
    return fmdb_oracle.run(Args())


def test_game_date_recorded_and_stable(report):
    meta = report['meta']
    assert meta['game_date_start']
    assert meta['game_date_end'] == meta['game_date_start'], 'the game day advanced during the run'


def test_every_sample_family_was_compared(report):
    for sample in ('player', 'staff', 'club', 'competition', 'stadium', 'city', 'currency'):
        assert report['meta']['sizes'].get(sample, 0) > 0, sample


def test_no_tool_errors(report):
    assert not report['tool_errors'], report['tool_errors']


def _row(report, key):
    return report['fields'][key]


@pytest.mark.parametrize('family', PINNED_FAMILIES)
def test_pinned_families_stay_at_full_agreement(report, family):
    rows = [r for r in report['fields'].values() if r['family'] == family]
    assert rows, family
    for r in rows:
        assert r['mismatch'] == 0, (r['field'], r['examples'])
        assert r['match'] + r['generic_unavailable'] + r['tool_unavailable'] > 0, r['field']


@pytest.mark.parametrize('key', PINNED_FIELDS)
def test_pinned_fields_stay_at_full_agreement(report, key):
    r = _row(report, key)
    assert r['mismatch'] == 0, (key, r['examples'])
    assert r['match'] + r['generic_unavailable'] + r['tool_unavailable'] > 0, key
