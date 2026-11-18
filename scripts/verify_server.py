from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:17865"


def get(path: str) -> tuple[int, str]:
    with urllib.request.urlopen(BASE + path) as response:
        return response.status, response.read().decode("utf-8")


def post(path: str) -> tuple[int, dict]:
    request = urllib.request.Request(BASE + path, method="POST", data=b"")
    with urllib.request.urlopen(request) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def main() -> int:
    status, health = get("/health")
    print("health", status, health)
    status, html = get("/")
    print("preview", status, "start" if 'id="start"' in html else "missing-start")
    print("preview stop", "ok" if 'id="stop"' in html else "missing")
    print("preview close", "ok" if 'aria-label="Close"' in html else "missing")
    status, snapshot = get("/status")
    print("status", status, snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
