"""Exact checked PERSON joins into one current competition counter population."""

from . import assessment_people, virtual_identity
from .league_player_ranking import METRICS, SCOPE


def bound_subject(read, base, tables, people, binding):
    """Rebind actual/combined or a stored compact virtual identity, never generate."""
    if type(binding) is not dict:
        raise ValueError("Invalid competition player reference binding")
    if binding.get("record_kind") != "virtual":
        return assessment_people.bound_player(read, base, tables, people, binding)
    if (
        binding.get("tables") != tables
        or binding.get("binding_kind") != virtual_identity.BINDING_KIND
        or binding.get("person_offset") != 0x20
        or type(binding.get("database_index")) is not int
        or type(binding.get("identity")) is not tuple
    ):
        raise ValueError("Use an available-policy stored virtual player reference")
    core = virtual_identity.inspect(read, binding["address"], tables)
    saved = binding["identity"]
    if len(saved) != len(core["identity"]) or any(
        type(a) is not type(b) for a, b in zip(saved, core["identity"])
    ):
        raise ValueError("Invalid stored virtual reference identity")
    if (
        binding.get("database_index") != core["native_identity"]["database_index"]
        or binding.get("identity") != core["identity"]
    ):
        raise assessment_people.StalePlayerReference(
            "Stored virtual competition reference changed"
        )
    return binding["address"] + 0x20, {
        "display_name": None,
        "native_identity": core["native_identity"],
        "record_kind": "virtual",
    }


def project(coverage, candidates, requested):
    """Preserve requested order/duplicates; missing native counters remain unknown.

    requested entries are (player_ref, canonical PERSON address, checked public
    identity). No addresses or collector-private fields leave this function.
    """
    if not 1 <= len(requested) <= 100:
        raise ValueError("Supply 1 through 100 checked subjects")
    indexed = {}
    for row in candidates:
        index = row["person_index"]
        if type(index) is not int or index < 0 or index in indexed:
            raise ValueError("Duplicate or invalid competition PERSON rows")
        indexed[index] = row
    if coverage["source_state"] not in ("available", "unavailable"):
        raise ValueError("Invalid competition source state")
    available = coverage["source_state"] == "available"
    if available and (
        coverage.get("complete_resident_pool") is not True
        or coverage.get("physical_count") != len(candidates)
    ):
        raise ValueError("Incomplete competition counter population")
    if not available and candidates:
        raise ValueError("Unavailable source has counter rows")
    rows = []
    for ordinal, (reference, person_address, public) in enumerate(requested):
        identity = public["native_identity"]
        index = identity["database_index"]
        if (
            type(index) is not int
            or index < 0
            or public["record_kind"] not in ("actual", "player_staff", "virtual")
        ):
            raise ValueError("Unsupported checked competition player identity")
        candidate = indexed.get(index) if available else None
        state = (
            "observed_competition_counter"
            if candidate is not None
            else "not_observed_in_resident_pool"
            if available
            else "source_unavailable"
        )
        item = {
            "request_index": ordinal,
            "player_ref": reference,
            "person_index": index,
            "person": public,
            "state": state,
            "source_row_index": None,
            **{key: None for key in METRICS},
            "metric_states": {key: state for key in METRICS},
            "raw": None,
            "last_associated_team_index": None,
            "last_associated_team": None,
        }
        if candidate is not None:
            native = candidate.get("_identity")
            offset = (
                0x388
                if public["record_kind"] == "actual"
                else 0x480
                if public["record_kind"] == "player_staff"
                else 0x20
            )
            if (
                native is None
                or native["native_identity"] != identity
                or native["record_kind"] != public["record_kind"]
                or candidate["_primary_address"] + offset != person_address
            ):
                raise ValueError(
                    "Requested PERSON and competition counter identity disagree"
                )
            item.update(
                {
                    key: candidate[key]
                    for key in (
                        *METRICS,
                        "metric_states",
                        "raw",
                        "last_associated_team_index",
                        "last_associated_team",
                    )
                }
            )
            item["source_row_index"] = candidate["source_ordinal"]
        rows.append(item)
    return {
        "rows": rows,
        "requested_count": len(rows),
        "unique_requested_person_count": len({row["person_index"] for row in rows}),
        "observed_count": sum(
            row["state"] == "observed_competition_counter" for row in rows
        ),
        "not_observed_count": sum(
            row["state"] == "not_observed_in_resident_pool" for row in rows
        ),
        "unavailable_count": sum(row["state"] == "source_unavailable" for row in rows),
        "response_complete": True,
        "all_requested_rows_observed": all(
            row["state"] == "observed_competition_counter" for row in rows
        ),
        "all_requested_metrics_available": all(
            row["state"] == "observed_competition_counter"
            and all(row[key] is not None for key in METRICS)
            for row in rows
        ),
        "anomalous_metric_row_count": sum(
            any(
                state.startswith("anomalous_")
                for state in row["metric_states"].values()
            )
            for row in rows
        ),
        "limitations": SCOPE
        + " Requested-player order and duplicates are preserved. A missing resident counter row is unknown, never zero appearances or proof of no participation.",
    }
