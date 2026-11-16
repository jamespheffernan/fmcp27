"""Additive portable tables for independently guarded retained spatial packets.

Native average positions, official pass-map edges and derived sample density
remain different sources. Missing/unsupported sources never become empty maps.
"""
import json
import math

from .match_shot_dataset import _identity


def _number(value):
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
        raise ValueError('Spatial value must be finite or unknown')
    return value


def _integer(value, *, nullable=False):
    if nullable and value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError('Spatial count/index must be a nonnegative integer')
    return value


def _side(value):
    if type(value) is not int or value not in (0, 1):
        raise ValueError('Spatial fixture side must be home or away')
    return value


def _actor(db, fixture_id, side, person, name, slot=None):
    rows = db.execute('SELECT person_name,stored_player_slot FROM retained_players WHERE fixture_id=? AND side_index=? AND canonical_person_id=?', (fixture_id, side, person)).fetchall()
    if len(rows) != 1 or rows[0][0] != name or (slot is not None and rows[0][1] != slot):
        raise ValueError('Spatial actor is not uniquely bound to captured fixture player')


def write_spatial_reports(db, capture, selected, packets):
    """Require exact selected fixture identity and canonical per-side actor joins."""
    db.executescript('''
    CREATE TABLE spatial_packets(fixture_id TEXT PRIMARY KEY REFERENCES fixtures, native_match_key INTEGER,
      state TEXT NOT NULL, source_kind TEXT, raw_json TEXT NOT NULL);
    CREATE TABLE spatial_coverage(fixture_id TEXT REFERENCES fixtures, source TEXT NOT NULL,
      state TEXT NOT NULL, row_count INTEGER, raw_json TEXT NOT NULL,
      PRIMARY KEY(fixture_id,source));
    CREATE TABLE average_positions(fixture_id TEXT REFERENCES fixtures, native_match_key INTEGER,
      side_index INTEGER NOT NULL,stored_player_slot INTEGER NOT NULL,person_id INTEGER NOT NULL,
      person_name TEXT NOT NULL,state TEXT NOT NULL,sample_count INTEGER,sample_start_tick INTEGER,
      sample_step_native_ticks INTEGER,native_axis_0 REAL,native_axis_1 REAL,source_kind TEXT,raw_json TEXT NOT NULL,
      PRIMARY KEY(fixture_id,side_index,stored_player_slot));
    CREATE TABLE pass_edges(fixture_id TEXT REFERENCES fixtures,native_match_key INTEGER,
      side_index INTEGER NOT NULL,from_person_id INTEGER NOT NULL,from_name TEXT NOT NULL,
      to_person_id INTEGER NOT NULL,to_name TEXT NOT NULL,official_map_count INTEGER NOT NULL,
      counter_reconciled_completed_passes INTEGER,excluded_unlabelled_mask8_count INTEGER,
      source_state TEXT NOT NULL,raw_json TEXT NOT NULL,
      PRIMARY KEY(fixture_id,side_index,from_person_id,to_person_id));
    CREATE TABLE heatmap_grids(grid_id INTEGER PRIMARY KEY,fixture_id TEXT REFERENCES fixtures,
      native_match_key INTEGER,source_kind TEXT NOT NULL,scope TEXT NOT NULL,side_index INTEGER NOT NULL,
      stored_player_slot INTEGER,person_id INTEGER,person_name TEXT,state TEXT NOT NULL,
      axis_0_bins INTEGER NOT NULL,axis_1_bins INTEGER NOT NULL,axis_0_min REAL,axis_0_max REAL,
      axis_1_min REAL,axis_1_max REAL,official_rendered_heatmap_equivalence INTEGER,ui_oracle_verified INTEGER,
      retained_samples INTEGER,selected_samples INTEGER,binned_samples INTEGER,interpolated_points_binned INTEGER,normalization_json TEXT,axes_json TEXT NOT NULL,raw_json TEXT NOT NULL);
    CREATE TABLE heatmap_cells(grid_id INTEGER REFERENCES heatmap_grids,axis_0_index INTEGER,
      axis_1_index INTEGER,sample_count INTEGER,value REAL,value_kind TEXT NOT NULL,raw_json TEXT NOT NULL,
      PRIMARY KEY(grid_id,axis_0_index,axis_1_index));
    CREATE TABLE heatmap_interpolation_cells(grid_id INTEGER REFERENCES heatmap_grids,axis_0_index INTEGER,
      axis_1_index INTEGER,interpolation_count INTEGER NOT NULL,raw_json TEXT NOT NULL,
      PRIMARY KEY(grid_id,axis_0_index,axis_1_index));
    CREATE VIEW pass_edge_analysis AS SELECT f.date,f.home_team,f.away_team,p.* FROM pass_edges p JOIN fixtures f USING(fixture_id);
    CREATE VIEW average_position_analysis AS SELECT f.date,f.home_team,f.away_team,p.* FROM average_positions p JOIN fixtures f USING(fixture_id);
    ''')
    dump = lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False)
    captured = {}
    for item in capture.get('fixtures', ()):
        fixture = item.get('fixture', item); ref = fixture.get('fixture_ref')
        if ref:
            captured.setdefault(ref, []).append((fixture, item.get('native_match_key')))
    bound = {}
    for packet in packets:
        fixture = packet.get('fixture') or {}; ref = fixture.get('fixture_ref')
        candidates = captured.get(ref, ())
        if len(candidates) != 1:
            raise ValueError('Spatial packet requires one exact captured fixture reference')
        original, key = candidates[0]
        if _identity(fixture, require_complete=True) != _identity(original, require_complete=True) or packet.get('native_match_key') != key:
            raise ValueError('Spatial fixture identity or native match key disagrees with capture')
        if ref in bound:
            raise ValueError('Duplicate spatial packets for fixture')
        bound[ref] = packet
    for fid, fixture in selected:
        packet = bound.get(fixture.get('fixture_ref'))
        if packet is None:
            for source in ('average_positions','pass_network','sample_density','native_heat_map'):
                db.execute('INSERT INTO spatial_coverage VALUES(?,?,?,?,?)', (fid,source,'not_captured',None,'{}'))
            continue
        key = packet['native_match_key']
        db.execute('INSERT INTO spatial_packets VALUES(?,?,?,?,?)', (fid,key,packet['state'],packet.get('source_kind'),dump(packet)))
        for source in ('average_positions','pass_network','sample_density','native_heat_map'):
            value = packet.get(source)
            rows = value.get('players', ()) if value and source != 'pass_network' else [e for side in (value or {}).get('sides', ()) for e in side.get('edges', ())]
            db.execute('INSERT INTO spatial_coverage VALUES(?,?,?,?,?)', (fid,source,value.get('state','captured_per_side') if value else 'not_captured',len(rows) if value else None,dump(value)))
        averages = packet.get('average_positions') or {}
        for row in averages.get('players', ()):
            side, slot = _side(row['side_index']), _integer(row['stored_player_slot'])
            _actor(db,fid,side,row['canonical_person_id'],row['person_name'],slot)
            db.execute('INSERT INTO average_positions VALUES('+','.join('?' for _ in range(14))+')',
                       (fid,key,side,slot,row['canonical_person_id'],row['person_name'],row['state'],
                        _integer(row.get('sample_count'),nullable=True),row.get('sample_start_tick'),row.get('sample_step_native_ticks'),
                        _number(row.get('native_axis_0')),_number(row.get('native_axis_1')),averages.get('source_kind'),dump(row)))
        for side_row in (packet.get('pass_network') or {}).get('sides', ()):
            side = _side(side_row['side_index'])
            for row in side_row.get('edges', ()):
                _actor(db,fid,side,row['from_person_native_id'],row['from_name'])
                _actor(db,fid,side,row['to_person_native_id'],row['to_name'])
                db.execute('INSERT INTO pass_edges VALUES('+','.join('?' for _ in range(12))+')',
                           (fid,key,side,row['from_person_native_id'],row['from_name'],row['to_person_native_id'],row['to_name'],
                            _integer(row['official_map_count']),_integer(row.get('counter_reconciled_completed_passes'),nullable=True),
                            _integer(row.get('excluded_unlabelled_mask8_count'),nullable=True),side_row['state'],dump(row)))
        for name in ('sample_density','native_heat_map'):
            density = packet.get(name)
            if density:
                _write_grids(db,fid,key,density,dump,native=(name=='native_heat_map'))


def _write_grids(db, fid, key, packet, dump, *, native=False):
    axes = packet['axes']; a, b = axes['axis_0'], axes['axis_1']
    width, height = _integer(a['bins']), _integer(b['bins'])
    if len(packet.get('players',())) > 52 or len(packet.get('teams',())) > 2:
        raise ValueError('Spatial grid owner budget exceeded')
    for flag in ('official_rendered_heatmap_equivalence','ui_oracle_verified'):
        if packet.get(flag) is not None and type(packet[flag]) is not bool:
            raise ValueError('Spatial equivalence/oracle flags must be boolean or unknown')
    if not 0 < width * height <= 1000000:
        raise ValueError('Spatial grid budget exceeded')
    for scope, rows in (('player',packet.get('players', ())),('team',packet.get('teams', ()))):
        for row in rows:
            side = _side(row['side_index']); slot = row.get('stored_player_slot'); person = row.get('canonical_person_id'); name = row.get('person_name')
            if scope == 'player':
                _integer(slot); _actor(db,fid,side,person,name,slot)
            coverage = row.get('coverage') or {}; cells = row.get('cells') or []
            if len(cells) > width * height:
                raise ValueError('Spatial grid cell budget exceeded')
            state = row.get('state') or packet['state']
            cursor = db.execute('INSERT INTO heatmap_grids VALUES('+','.join('?' for _ in range(25))+')',
                     (None,fid,key,row.get('source_kind',packet['source_kind']),scope,side,slot,person,name,state,width,height,
                      _number(a.get('minimum')),_number(a.get('maximum')),_number(b.get('minimum')),_number(b.get('maximum')),
                      packet.get('official_rendered_heatmap_equivalence'),packet.get('ui_oracle_verified'),coverage.get('retained_samples'),coverage.get('selected_samples'),coverage.get('binned_samples'),coverage.get('interpolated_points_binned'),dump(row.get('postprocessing',packet.get('normalization'))),dump(axes),dump(row)))
            seen = set(); total = 0
            for cell in cells:
                x,y = _integer(cell['axis_0_index']),_integer(cell['axis_1_index'])
                if x >= width or y >= height or (x,y) in seen:
                    raise ValueError('Invalid or duplicate spatial grid cell')
                seen.add((x,y)); count = _integer(cell.get('sample_count'),nullable=True)
                if count is not None:total += count
                value = _number(cell.get('normalized_intensity') if native else cell.get('value'))
                if native and (count is not None or value is None):
                    raise ValueError('Native normalized heat intensity is not a sample count')
                db.execute('INSERT INTO heatmap_cells VALUES(?,?,?,?,?,?,?)',
                           (cursor.lastrowid,x,y,count,value,'native_normalized_intensity' if native else 'observed_sample_count' if count is not None else 'native_value',dump(cell)))
            if coverage.get('binned_samples') is not None and total != coverage['binned_samples']:
                raise ValueError('Spatial density cell sum differs from captured binned samples')
            raw_cells=row.get('raw_cells',())
            if len(raw_cells)>width*height:
                raise ValueError('Spatial interpolation cell budget exceeded')
            seen=set();interpolants=0
            for cell in raw_cells:
                x,y=_integer(cell['axis_0_index']),_integer(cell['axis_1_index'])
                count=_integer(cell['interpolation_count'])
                if x>=width or y>=height or (x,y) in seen:
                    raise ValueError('Invalid or duplicate interpolation grid cell')
                seen.add((x,y));interpolants+=count
                db.execute('INSERT INTO heatmap_interpolation_cells VALUES(?,?,?,?,?)',
                           (cursor.lastrowid,x,y,count,dump(cell)))
            if coverage.get('interpolated_points_binned') is not None and interpolants!=coverage['interpolated_points_binned']:
                raise ValueError('Native interpolation sum differs from captured source')
