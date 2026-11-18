"""Force the Windows Live Captions bar back on screen."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from livefeed.window import caption_hwnds, force_restore_all, snapshot_window


def main() -> int:
    hwnds = caption_hwnds()
    print("before", [(hwnd, snapshot_window(hwnd)) for hwnd in hwnds])
    restored = force_restore_all()
    hwnds = caption_hwnds()
    print("restored", restored)
    print("after", [(hwnd, snapshot_window(hwnd)) for hwnd in hwnds])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
