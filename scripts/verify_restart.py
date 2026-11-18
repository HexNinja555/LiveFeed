from __future__ import annotations

import json
import urllib.error
import urllib.request


def post(path: str) -> tuple[int, dict]:
    request = urllib.request.Request("http://127.0.0.1:17865" + path, method="POST", data=b"")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def main() -> int:
    for label, path in (("start1", "/start"), ("stop1", "/stop"), ("start2", "/start"), ("stop2", "/stop")):
        status, body = post(path)
        print(label, status, "running=", body.get("running"), "error=", body.get("error") or "")
        if status >= 400:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
