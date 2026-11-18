"""Save each capture session's transcript to logs/<date_time>.txt."""

from __future__ import annotations

import logging
import textwrap
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("livefeed.logbook")

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
WRITE_EVERY_S = 1.5


class TranscriptLog:
    """Rewrites the session file with the latest transcript, throttled.

    The transcript buffer can revise recent words, so the whole text is
    rewritten instead of appended; the file always matches what was shown.
    """

    def __init__(self, folder: Path = LOGS_DIR) -> None:
        self.folder = folder
        self.path: Path | None = None
        self._started: datetime | None = None
        self._text = ""
        self._written = ""
        self._last_write = 0.0

    def begin(self) -> None:
        self.finish()
        self._started = datetime.now()
        self.path = self.folder / f"{self._started:%Y-%m-%d_%H-%M-%S}.txt"
        self._text = ""
        self._written = ""
        self._last_write = 0.0

    def update(self, text: str) -> None:
        if self._started is None:
            return
        self._text = (text or "").strip()
        if time.monotonic() - self._last_write >= WRITE_EVERY_S:
            self._flush()

    def finish(self) -> None:
        if self._started is None:
            return
        self._flush()
        self._started = None

    def _flush(self) -> None:
        self._last_write = time.monotonic()
        if not self._text or self._text == self._written or self.path is None:
            return
        header = f"LiveFeed caption log - started {self._started:%Y-%m-%d %H:%M:%S}\n"
        footer = f"Last updated {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        body = textwrap.fill(self._text, width=100)
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            self.path.write_text(f"{header}\n{body}\n\n{footer}", encoding="utf-8")
            self._written = self._text
        except OSError:
            log.exception("Could not write caption log %s", self.path)
