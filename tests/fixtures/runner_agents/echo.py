"""Echo fixture — reads JSON from stdin, echoes structured response on stdout."""

import json
import os
import sys


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"raw": raw}
    response = {
        "received": payload,
        "env_probe": os.environ.get("AGENTANVIL_PROBE", ""),
    }
    json.dump(response, sys.stdout)


if __name__ == "__main__":
    main()
