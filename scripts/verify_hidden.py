from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from livefeed.captions import caption_window_open, read_caption_text
from livefeed.window import caption_hwnds, snapshot_window

BASE = "http://127.0.0.1:17865"


def post(path: str) -> dict:
    request = urllib.request.Request(BASE + path, method="POST", data=b"")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def describe() -> None:
    hwnds = caption_hwnds()
    print("hwnds", hwnds, "attached", caption_window_open())
    for hwnd in hwnds:
        snap = snapshot_window(hwnd)
        print(
            " ",
            hwnd,
            "visible",
            snap.visible,
            "pos",
            (snap.left, snap.top, snap.width, snap.height),
        )
    print(" text", repr(read_caption_text()[:80]))


def main() -> int:
    print("before")
    describe()
    started = post("/start")
    print("start running", started.get("running"), "live_len", len(started.get("live") or ""))
    time.sleep(0.6)
    print("capturing")
    describe()
    stopped = post("/stop")
    print("stop running", stopped.get("running"))
    time.sleep(0.3)
    print("after")
    describe()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
