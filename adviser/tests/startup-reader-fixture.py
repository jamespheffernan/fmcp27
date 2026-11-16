"""An isolated MCP reader that can fail before discovery. It never opens a save."""
import json
import os
from pathlib import Path
import sys
import time

directory = Path(os.environ["PI_FM_TEST_READER_DIR"])
attempts = directory / "attempts"
number = int(attempts.read_text()) + 1 if attempts.exists() else 1
attempts.write_text(str(number))
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    row = {"attempt": number, "method": method}
    if method == "tools/call":
        # Which tool was called: a test can tell the harness's own fm_attach from a model's read.
        row["name"] = message.get("params", {}).get("name")
    with (directory / "requests.jsonl").open("a") as log:
        log.write(json.dumps(row) + "\n")
    if method == "initialize":
        (directory / "cache-env.json").write_text(json.dumps(os.environ.get("FMCP_CACHE_DIR")))
        if number == 1:
            time.sleep(float(os.environ.get("PI_FM_TEST_FIRST_DELAY", "0")))
        if number <= int(os.environ.get("PI_FM_TEST_FAILED_STARTS", "0")):
            print("simulated reader initialization failure", file=sys.stderr, flush=True)
            sys.exit(9)
        result = {"protocolVersion": message["params"]["protocolVersion"], "capabilities":{"tools":{}},
                  "serverInfo":{"name":"fm-fixture","version":"1"}}
    elif method == "tools/list":
        result = {"tools":[{"name":"fm_status","description":"Return the startup fixture's status.",
                            "inputSchema":{"type":"object","properties":{}},"annotations":{"readOnlyHint":True}}]}
    elif method == "tools/call":
        result = {"content":[{"type":"text","text":"ready"}]}
    elif "id" in message:
        result = {}
    else:
        continue
    print(json.dumps({"jsonrpc":"2.0","id":message["id"],"result":result}),flush=True)
