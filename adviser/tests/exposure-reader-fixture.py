"""An isolated MCP reader offering the tool names in PI_FM_TEST_TOOLS. It never opens a save.

Like the real reader, most tools require a session_id from fm_attach; fm_status, fm_attach and the
screen tools do not. Requests are logged with their arguments to PI_FM_TEST_READER_DIR/requests.jsonl.
  PI_FM_TEST_ATTACH_ERROR   fm_attach fails with this message
  PI_FM_TEST_EXPIRE_ON      the first call of this tool finds the session expired (a game restart)
  PI_FM_TEST_WRITERS        comma-separated tool names offered without the read-only annotation
"""
import json
import os
from pathlib import Path
import sys

directory = Path(os.environ["PI_FM_TEST_READER_DIR"])
names = [n for n in os.environ.get("PI_FM_TEST_TOOLS", "fm_status").split(",") if n]
attach_error = os.environ.get("PI_FM_TEST_ATTACH_ERROR")
expire_on = os.environ.get("PI_FM_TEST_EXPIRE_ON")
writers = {n for n in os.environ.get("PI_FM_TEST_WRITERS", "").split(",") if n}
NO_SESSION = {"fm_status", "fm_attach", "fm_get_inbox", "fm_get_board_confidence", "fm_get_calendar",
              "fm_get_squad_happiness", "fm_get_player_status", "fm_get_club_vision_progress",
              "fm_get_league_table", "fm_get_match", "fm_coverage"}
DESCRIPTIONS = {
    "fm_get_retained_shot_map": "Read shot events for one retained completed match: shot map with locations, outcomes and xG.",
    "fm_find_fixtures": "Find fixtures and results by team, competition and date.",
    "fm_db_query": "Run one read-only SELECT over the SQLite snapshot of the save.",
}
state = {"session": None, "attaches": 0, "expired": False}


def tool(name):
    props = {} if name in NO_SESSION else {"session_id": {"type": "string"}}
    if name == "fm_db_query":
        props.update({"sql": {"type": "string"}, "view": {"type": "string", "enum": ["full", "manager"]}})
    if name == "fm_db_schema":
        props.update({"table": {"type": "string"}, "include_pending": {"type": "boolean"}, "view": {"type": "string"}})
    schema = {"type": "object", "properties": props}
    if "session_id" in props:
        schema["required"] = ["session_id"] + (["sql"] if name == "fm_db_query" else [])
    return {"name": name, "description": DESCRIPTIONS.get(name, f"Fixture reader tool {name}."),
            "inputSchema": schema, "annotations": {"readOnlyHint": name not in writers}}


def text(value, error=False):
    out = {"content": [{"type": "text", "text": json.dumps(value, indent=2) if not isinstance(value, str) else value}]}
    if error:
        out["isError"] = True
    return out


def call(name, args):
    if name == "fm_attach":
        if attach_error:
            return text(f"Error executing tool fm_attach: {attach_error}", True)
        state["attaches"] += 1
        state["session"] = f"S{state['attaches']}"
        return text({"session_id": state["session"], "memory_access": "verified"})
    if name not in NO_SESSION:
        if expire_on == name and not state["expired"]:
            state["expired"] = True
            state["session"] = None
        if args.get("session_id") is None or args.get("session_id") != state["session"]:
            return text(f"Error executing tool {name}: Unknown session. Call fm_attach first.", True)
    if name == "fm_get_save":
        return text({"session_id": args["session_id"], "save": {
            "name": "Fixture Career", "current_date": os.environ.get("PI_FM_TEST_GAME_DATE", "2030-12-13"),
            "last_saved_date": "2030-12-11",
            "coaches": [{"name": "Test  Manager", "club": {"name": "Fixture United", "short_name": "Fixture"}}]}})
    if name == "fm_db_schema":
        if args.get("table"):
            cols = {"player_view": ["idx", "name", "age", "club", "team_idx", "wage", "pace"]}.get(args["table"], ["idx"])
            return text({"table": args["table"], "columns": [{"column": c} for c in cols]})
        return text({"game_date": "2030-12-13", "tables": {"player": {}, "match": {}}, "views": {"player_view": {}}})
    if name == "fm_db_query":
        return text({"columns": ["idx", "name"], "rows": [[1, "A"], [2, "B"]], "row_count": 2,
                     "truncated": False, "session_seen": args.get("session_id")})
    return text({"fixture": name, "session_seen": args.get("session_id")})


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    entry = {"method": method}
    if method == "tools/call":
        entry["name"] = message["params"]["name"]
        entry["args"] = message["params"].get("arguments", {})
    with (directory / "requests.jsonl").open("a") as log:
        log.write(json.dumps(entry) + "\n")
    if method == "initialize":
        result = {"protocolVersion": message["params"]["protocolVersion"], "capabilities": {"tools": {}},
                  "serverInfo": {"name": "fm-exposure-fixture", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [tool(n) for n in names]}
    elif method == "tools/call":
        result = call(message["params"]["name"], message["params"].get("arguments") or {})
    elif "id" in message:
        result = {}
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
