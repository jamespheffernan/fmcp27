"""Private publisher subprocess; only the fixed generator calls this protocol."""

import base64, json, sys
from report_output import publish

if __name__ == "__main__":
    try:
        raw = sys.stdin.buffer.read(90 * 1024 * 1024 + 1)
        if len(raw) > 90 * 1024 * 1024:
            raise ValueError("Publication input exceeds bound")
        value = json.loads(raw)
        if not {"data", "html_base64"} <= value.keys() or value.keys() - {
            "data", "html_base64", "filename"
        }:
            raise ValueError("Invalid publisher protocol")
        result = publish(
            value["data"], base64.b64decode(value["html_base64"], validate=True),
            filename=value.get("filename")
        )
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
