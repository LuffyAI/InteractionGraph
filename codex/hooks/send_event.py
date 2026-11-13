#!/usr/bin/env python3
"""Forward the hook JSON from stdin without changing the conversation."""
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("expected an event object")
        endpoint = os.environ.get("CODEX_SERVER_URL", "http://127.0.0.1:8765/events")
        request = urllib.request.Request(
            endpoint, data=json.dumps(event, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        # Local event forwarding should not be routed through an HTTP proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=1) as response:
            response.read()
    except (ValueError, OSError, urllib.error.URLError) as error:
        print(f"codex: event not delivered: {error}", file=sys.stderr)
    # Stdout is reserved for the hook protocol. Never inject log text into it.
    print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
