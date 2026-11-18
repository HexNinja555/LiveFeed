from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:17865"


def post(path: str) -> tuple[int, dict]:
    request = urllib.request.Request(BASE + path, method="POST", data=b"")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"error": body}
        return exc.code, payload


def main() -> int:
    start_status, started = post("/start")
    print("start", start_status, json.dumps(started, indent=2))
    stop_status, stopped = post("/stop")
    print("stop", stop_status, json.dumps(stopped, indent=2))
    return 0 if start_status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
