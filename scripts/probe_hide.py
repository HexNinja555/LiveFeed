"""Try hide strategies and report whether UI Automation still attaches."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from livefeed.captions import (
    caption_window_open,
    launch_live_captions,
    read_caption_text,
    wait_for_caption_window,
)
from livefeed.window import (
    apply_hide,
    caption_hwnds,
    restore_window,
    snapshot_window,
)


def report(label: str) -> None:
    hwnds = caption_hwnds()
    attached = caption_window_open()
    text = read_caption_text()
    print(f"{label:18} hwnds={hwnds} attached={attached} text={text!r}")


def main() -> int:
    launch_live_captions()
    wait_for_caption_window()
    hwnds = caption_hwnds()
    if not hwnds:
        print("no hwnd")
        return 1
    original = {hwnd: snapshot_window(hwnd) for hwnd in hwnds}
    report("visible")
    for method in ("cloak", "transparent", "offscreen", "hide"):
        for hwnd in hwnds:
            restore_window(hwnd, original[hwnd])
        time.sleep(0.2)
        for hwnd in hwnds:
            apply_hide(hwnd, method)
        time.sleep(0.4)
        report(method)
        for hwnd in hwnds:
            restore_window(hwnd, original[hwnd])
        time.sleep(0.2)
    report("restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
