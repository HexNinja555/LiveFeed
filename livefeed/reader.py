"""Poll Live Captions on a worker thread and push each new line."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable

from livefeed.captions import (
    bind_uia,
    element_alive,
    extract_caption,
    launch_live_captions,
    locate_window,
    unbind_uia,
    wait_for_caption_window,
)
from livefeed.errors import CaptionError
from livefeed.window import CaptionBarHider

log = logging.getLogger("livefeed.reader")

POLL_S = 0.08
STOP_JOIN_S = 0.75
EMPTY_HOLD_S = 0.3


class CaptionLine:
    __slots__ = ("text", "partial")

    def __init__(self, text: str, *, partial: bool = True) -> None:
        self.text = text
        self.partial = partial


class LiveCaptionReader:
    """Start Live Captions, poll the bar, emit changed (and boundary-empty) lines."""

    def __init__(self, *, poll_s: float = POLL_S, hide_system_bar: bool = True) -> None:
        self.poll_s = poll_s
        self._hider = CaptionBarHider() if hide_system_bar else None
        self._queue: asyncio.Queue[CaptionLine | None] | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: threading.Event | None = None

    @property
    def worker_alive(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    async def start(self) -> None:
        if self.worker_alive:
            raise CaptionError(
                "The previous Live Captions reader is still stopping.",
                detail="Wait a moment, then start capture again.",
            )
        await asyncio.to_thread(launch_live_captions)
        await asyncio.to_thread(wait_for_caption_window)
        if self._hider is not None:
            try:
                await asyncio.to_thread(self._hider.hide)
            except Exception:
                log.exception("Could not hide the Live Captions bar")
        try:
            self._queue = asyncio.Queue()
            self._loop = asyncio.get_running_loop()
            self._stop = threading.Event()
            self._thread = threading.Thread(
                target=self._poll,
                args=(self._stop,),
                name="livefeed-captions",
                daemon=True,
            )
            self._thread.start()
        except Exception:
            if self._hider is not None:
                await asyncio.to_thread(self._hider.restore)
            raise
        log.info("Reading Windows 11 Live Captions")

    async def stop(self) -> None:
        stop = self._stop
        if stop is not None:
            stop.set()
        queue = self._queue
        self._queue = None
        self._loop = None
        if queue is not None:
            queue.put_nowait(None)
        thread = self._thread
        if thread and thread.is_alive():
            loop = asyncio.get_running_loop()
            deadline = loop.time() + STOP_JOIN_S
            while thread.is_alive() and (deadline - loop.time()) > 0:
                await asyncio.sleep(min(0.025, deadline - loop.time()))
        if thread is not None and thread.is_alive():
            log.warning("Live Captions reader did not stop within %.2f s", STOP_JOIN_S)
        elif self._thread is thread:
            self._thread = None

    def abandon(self) -> None:
        """Drop a stuck worker so a new reader can start."""
        if self._stop is not None:
            self._stop.set()
        if self._hider is not None:
            self._hider.forget()
            self._hider = None
        self._queue = None
        self._loop = None
        self._thread = None

    async def lines(self) -> AsyncIterator[CaptionLine]:
        queue = self._queue
        if queue is None:
            return
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    def _poll(self, stop: threading.Event) -> None:
        last = ""
        empty_since: float | None = None
        last_hide = 0.0
        automation = None
        try:
            automation, uia = bind_uia()
            while not stop.is_set():
                now = time.monotonic()
                if self._hider is not None and now - last_hide >= 0.5:
                    try:
                        self._hider.maintain()
                    except Exception:
                        log.exception("Could not keep the Live Captions bar hidden")
                    last_hide = now
                try:
                    window = locate_window(automation, uia)
                    text = extract_caption(automation, uia, window) if element_alive(window) else ""
                except Exception:
                    log.exception("Live Captions read failed")
                    stop.wait(0.4)
                    continue
                if text:
                    empty_since = None
                    if text != last:
                        last = text
                        self._push(text)
                elif last:
                    now = time.monotonic()
                    if empty_since is None:
                        empty_since = now
                    elif now - empty_since >= max(EMPTY_HOLD_S, self.poll_s * 3):
                        # A cleared bar is an utterance boundary. Without this
                        # reset, repeating the same sentence looks unchanged.
                        last = ""
                        empty_since = None
                        self._push("")
                stop.wait(self.poll_s)
        finally:
            if automation is not None:
                unbind_uia()
            if self._hider is not None:
                self._hider.restore()

    def _push(self, text: str) -> None:
        loop = self._loop
        queue = self._queue
        if loop is None or queue is None:
            return
        try:
            loop.call_soon_threadsafe(queue.put_nowait, CaptionLine(text, partial=True))
        except RuntimeError:
            pass


def watch_captions(
    on_line: Callable[[str], None],
    *,
    stop: threading.Event,
    poll_s: float = POLL_S,
) -> None:
    """Synchronous poll helper for callers that do not use asyncio."""
    last = ""
    empty_since: float | None = None
    automation, uia = bind_uia()
    try:
        while not stop.is_set():
            try:
                window = locate_window(automation, uia)
                text = extract_caption(automation, uia, window) if element_alive(window) else ""
            except Exception:
                log.exception("Live Captions read failed")
                stop.wait(0.4)
                continue
            if text:
                empty_since = None
                if text != last:
                    last = text
                    on_line(text)
            elif last:
                now = time.monotonic()
                if empty_since is None:
                    empty_since = now
                elif now - empty_since >= max(EMPTY_HOLD_S, poll_s * 3):
                    last = ""
                    empty_since = None
                    on_line("")
            stop.wait(poll_s)
    finally:
        unbind_uia()
