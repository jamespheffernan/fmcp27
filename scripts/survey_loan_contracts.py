"""Read-only census of player loan objects, with checked production decodes."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import database, loan_contracts, players, wages, world
from fm_live_mcp.bridge import Bridge


def main():
    b = Bridge()
    sid = b.attach()['session_id']
    counts, samples, errors, competition_conditions = Counter(), {}, [], []
    seen = 0
    try:
        for lower in range(0, 200000, 5000):
            with b.lock, b._read_scope(sid):
                p = b.process
                tables = b._player_layout(p)
                base = tables[0] - players.RVA[0]
                read = lambda a, n: b._read_memory(p, a, n)
                info = database.table(read, base, 'people')
                if lower >= info['count']:
                    break
                currency = wages.base_currency(read, base)
                layouts = {tables[2]: 0x388, base + players.STAFF_RVA[2]: 0x480}
                for start in range(lower, min(lower + 5000, info['count']), 1000):
                    n = min(1000, info['count'] - start, lower + 5000 - start)
                    for index, person in enumerate(struct.unpack(f'<{n}Q', read(info['start'] + start * 8, n * 8)), start):
                        seen += 1
                        offset = layouts.get(players.u64(read(person, 8)))
                        if offset is None:
                            counts['other_person_type'] += 1
                            continue
                        holder = players.u64(read(person - 0x90, 8))
                        if not holder:
                            counts['no_holder'] += 1
                            continue
                        loan = players.u64(read(holder, 8))
                        if not loan:
                            counts['empty_current_loan_slot'] += 1
                            continue
                        if players.u64(read(loan, 8)) != base + world.TYPES['loan_contract'][0]:
                            counts['other_auxiliary_contract_type'] += 1
                            continue
                        try:
                            snap, _, _ = b._world_state(p, tables)
                            database.player_membership(snap, base, database.table(snap, base, 'people'), index, person - offset)
                            row = players.decode(snap, person - offset, tables)[0]
                            result = loan_contracts.decode(snap, base, person - offset, offset, currency)
                            snap.verify()
                        except Exception as exc:
                            errors.append({'index': index, 'error': str(exc)})
                            counts['rejected'] += 1
                            continue
                        counts['decoded'] += 1
                        trigger = result['purchase']['trigger']
                        counts[trigger] += 1
                        keys = [trigger, result['current_club_relationship'], result['parent_club_state']]
                        source = 'clause_flags_' + result['clause_flags']['source']
                        counts[source] += 1
                        keys.append(source)
                        for clause, present in result['clauses'].items():
                            if present:
                                counts[clause] += 1
                                keys.append(clause)
                        if int(result['clause_flags']['unmapped_flags_hex'], 16):
                            counts['unmapped_clause_flags'] += 1
                            keys.append('unmapped_clause_flags')
                        for field in loan_contracts.CASH_FIELDS:
                            amount = result[field]['amount']
                            if amount is not None and amount > 0:
                                counts[field + '_positive'] += 1
                                keys.append(field + '_positive')
                        if result['purchase']['additional_fee_components']:
                            counts['with_fee_components'] += 1
                            keys.append('with_fee_components')
                        if offset == 0x480:
                            counts['combined'] += 1
                            keys.append('combined')
                        sample = {'name': row['name'], 'birth_date': row['birth_date'],
                                  'database_index': index, 'loan_contract': result}
                        condition = result['purchase']['competition_condition']
                        if condition is not None:
                            competition_conditions.append(sample)
                            counts['competition_' + condition['state']] += 1
                            counts['achievement_code_' + str(condition['native_achievement_code'])] += 1
                        for key in keys:
                            samples.setdefault(key, sample)
            print('scanned', seen, 'loans', counts['decoded'], 'rejected', counts['rejected'], flush=True)
    finally:
        b.detach()
        receipt = {'observed_at': datetime.now(timezone.utc).isoformat(), 'seen': seen,
                   'native_person_count': info['count'], 'complete_native_table_scan': seen == info['count'],
                   'counts': dict(counts), 'samples': samples, 'errors': errors,
                   'competition_conditions': competition_conditions,
                   'scope': 'Best-effort census; each decoded loan has save, identity, membership and consumed-byte rechecks. No UI.'}
        (ROOT/'evidence/loan-contract-survey.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt['counts']))


if __name__ == '__main__':
    main()
