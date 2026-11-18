"""User-facing errors for Live Captions capture."""

from __future__ import annotations


class LiveFeedError(Exception):
    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def display(self) -> str:
        extra = (self.detail or "").strip()
        if extra:
            return f"{self.message}\n\n{extra}"
        return self.message


class CaptionError(LiveFeedError):
    """Live Captions could not be started, attached, or read."""
