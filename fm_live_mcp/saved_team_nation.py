"""Resolve the saved TEAM owner chain and retain independent language provenance."""
from . import saved_database, saved_national_containers, saved_nation_labels, saved_nations


class NationContext:
    def __init__(self, reader):
        self.nations = list(saved_database.table(reader, 'NATION', saved_nations.read_nation_identity))
        self.containers = []
        self.claims = {}
        team_slots = 0
        for owner in saved_database.table(reader, 'NATIONAL_TEAM_CONTAINER',
                                          saved_national_containers.read_national_container):
            nation_index = owner['nation_index']
            if nation_index is not None and not 0 <= nation_index < len(self.nations):
                raise ValueError('Saved national container NATION index is outside the saved table')
            team_slots += len(owner['team_indices'])
            if team_slots > 1_000_000:
                raise ValueError('Saved national container TEAM vectors exceed the lookup budget')
            self.containers.append(owner)
            for index in set(owner['team_indices']):
                if index is None:
                    continue
                if index < 0 or index >= 250_000:
                    raise ValueError('Saved national container TEAM index is outside supported bounds')
                self.claims.setdefault(index, []).append(owner['database_index'])
        # The same team can legitimately appear in multiple container vectors.
        # The saved TEAM owner word identifies its container in this query.

    def resolve(self, team):
        if team['owner_kind'] != 'national':
            return None
        index = team['database_index']
        owner_index = team['owner_index']
        claimed_by = self.claims.get(index, ())
        result = {'state': 'no_saved_owner', 'container': None, 'nation': None,
                  'owner_team_slots': [], 'installed_english': None}
        competing = [claim for claim in claimed_by if claim != owner_index]
        if competing:
            result['other_claiming_container_indices'] = competing
        if owner_index is not None:
            if not 0 <= owner_index < len(self.containers):
                raise ValueError('Saved TEAM national container owner is outside the saved table')
            owner = self.containers[owner_index]
            result['container'] = {key: owner[key] for key in ('database_index', 'native_id', 'secondary_id')}
            result['owner_team_slots'] = [slot for slot, ref in enumerate(owner['team_indices']) if ref == index]
            nation_index = owner['nation_index']
            result['nation'] = self.nations[nation_index] if nation_index is not None else None
            result['state'] = 'saved_nation' if nation_index is not None else 'no_saved_nation'
        return result

    def finish(self, total_teams, selected):
        if any(index >= total_teams for index in self.claims):
            raise ValueError('Saved national container TEAM index is outside the saved table')
        national_rows = [row['nation_context'] for row in selected if row.get('nation_context', {}).get('nation')]
        if not national_rows:
            return {'status': 'not_needed', 'reason': None, 'metadata': {}}
        source = saved_nation_labels.load_english_nation_labels()
        for context in national_rows:
            label = source['labels'].get(context['nation']['native_id'])
            if label is not None:
                context['installed_english'] = {key: label[key] for key in ('name', 'short_name', 'abbreviation')}
        return {key: source[key] for key in ('status', 'reason', 'metadata')}
