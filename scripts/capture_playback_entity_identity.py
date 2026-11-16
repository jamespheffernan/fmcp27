"""Research capture mode: one exact current playback frame, no native calls."""

from pathlib import Path
import argparse
import hashlib
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fm_live_mcp.bridge import Bridge
from fm_live_mcp import (
    active_match_entity_identity,
    active_match_playback,
    active_match_source,
    players,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--helper", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a fresh evidence filename")
    bridge = Bridge(helper=args.helper)
    session = bridge.attach()["session_id"]
    try:
        with bridge.lock, bridge._read_scope(session):
            process = bridge._current(session)
            tables = bridge._player_layout(process)
            read, save, epoch = bridge._world_state(process, tables)
            base = tables[0] - players.RVA[0]
            context, private = active_match_source.inspect_context(
                read, base, expected_current_date=save["current_date"]
            )
            result = {
                "state": "unavailable_current_fixture_bound_match",
                "players": None,
                "active_xi_verified": False,
                "nearest_opponent": None,
            }
            if private is not None:
                playback = active_match_playback.capture(
                    read, base, client=private["client"]
                )
                if playback["state"] == "bound_playback_cursor":
                    result = active_match_entity_identity.inspect_bound(
                        read,
                        base,
                        private["client"],
                        private["engine"],
                        playback["bound_playback"],
                    )
                else:
                    result["reason"] = playback["state"]
            read.verify()
            ending, ending_save, ending_epoch = bridge._world_state(
                bridge._current(session), tables
            )
            ending.verify()
            if ending_epoch != epoch:
                raise ValueError("Career/process epoch changed during entity capture")
            if result.get("players"):
                result["online_positive_control_verified"] = True
            result["caller_readset_and_epoch_verification_required"] = False
            packet = {
                "save": bridge._public_save(save),
                "context": context,
                "epoch_sha256": hashlib.sha256(repr(epoch).encode()).hexdigest(),
                "same_process_career_epoch_verified": True,
                "strict_readset_verified": True,
                "source_policy": "one exact already resident cursor frame; no historical fallback; changed sources reject",
                "game_writes": False,
                "native_functions_executed": False,
                "UI": False,
                "result": result,
            }
    finally:
        bridge.detach()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(packet, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "state": packet["result"]["state"],
                "resolved_entities": len(packet["result"].get("players") or []),
                "strict_readset_verified": True,
                "output": str(args.output.resolve()),
            }
        )
    )


if __name__ == "__main__":
    main()
