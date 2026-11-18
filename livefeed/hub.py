"""Own start/stop of the caption reader and fan out transcript updates."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from livefeed.errors import CaptionError, LiveFeedError
from livefeed.logbook import TranscriptLog
from livefeed.overlay import CaptionOverlay
from livefeed.reader import LiveCaptionReader
from livefeed.transcript import TranscriptBuffer, TranscriptView
from livefeed.window import force_restore_all

log = logging.getLogger("livefeed.hub")

Listener = Callable[[dict], None]


@dataclass
class CaptureState:
    running: bool = False
    starting: bool = False
    error: str = ""
    live: str = ""
    committed: str = ""
    provisional: str = ""
    full: str = ""
    extension_clients: int = 0

    def as_dict(self) -> dict:
        return {
            "type": "status",
            "running": self.running,
            "starting": self.starting,
            "error": self.error,
            "live": self.live,
            "committed": self.committed,
            "provisional": self.provisional,
            "full": self.full,
            "extension_clients": self.extension_clients,
            "extension_connected": self.extension_clients > 0,
        }

    def caption_event(self) -> dict:
        payload = self.as_dict()
        payload["type"] = "caption"
        return payload


@dataclass
class CaptionHub:
    reader: LiveCaptionReader = field(default_factory=LiveCaptionReader)
    buffer: TranscriptBuffer = field(default_factory=TranscriptBuffer)
    overlay: CaptionOverlay = field(default_factory=CaptionOverlay)
    state: CaptureState = field(default_factory=CaptureState)
    transcript_log: TranscriptLog = field(default_factory=TranscriptLog)
    _listen_task: asyncio.Task[None] | None = None
    _listeners: list[Listener] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _loop: asyncio.AbstractEventLoop | None = None

    def __post_init__(self) -> None:
        self.overlay.on_inject = self.inject_caption

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def snapshot(self) -> dict:
        return self.state.as_dict()

    def add_extension_client(self) -> None:
        self.state.extension_clients += 1
        self._publish(self.snapshot())

    def remove_extension_client(self) -> None:
        self.state.extension_clients = max(0, self.state.extension_clients - 1)
        self._publish(self.snapshot())

    def inject_caption(self, text: str) -> None:
        payload = (text or "").strip()
        if not payload:
            return
        event = {**self.snapshot(), "type": "inject", "text": payload}

        def emit() -> None:
            for listener in list(self._listeners):
                try:
                    listener(event)
                except Exception:
                    log.exception("Caption inject listener failed")

        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(emit)
        else:
            emit()

    async def start(self) -> dict:
        self.bind_loop(asyncio.get_running_loop())
        async with self._lock:
            if self.state.running or self.state.starting:
                self.state.error = ""
                if self.state.running:
                    try:
                        await asyncio.to_thread(self.overlay.show)
                    except Exception:
                        log.exception("Could not show the desktop caption overlay")
                return self.snapshot()
            if self.reader.worker_alive:
                log.warning("Previous Live Captions reader is still stopping; starting a new one")
                self.reader.abandon()
                self.reader = LiveCaptionReader()
            self.state.starting = True
            self.state.error = ""
            self._publish(self.snapshot())
            try:
                self.buffer.clear()
                self.state.live = ""
                self.state.committed = ""
                self.state.provisional = ""
                self.state.full = ""
                await self.reader.start()
            except Exception as exc:
                try:
                    await self.reader.stop()
                except Exception:
                    log.exception("Error cleaning up a failed caption start")
                self.state.starting = False
                self.state.running = False
                self.state.error = self._format(exc)
                self._publish(self.snapshot())
                raise
            self.state.starting = False
            self.state.running = True
            self.transcript_log.begin()
            self._listen_task = asyncio.create_task(self._pump(), name="livefeed-pump")
            try:
                await asyncio.to_thread(self.overlay.show)
            except Exception:
                log.exception("Could not show the desktop caption overlay")
            self._publish(self.snapshot())
            return self.snapshot()

    async def stop(self) -> dict:
        async with self._lock:
            self.state.running = False
            self.state.starting = False
            task = self._listen_task
            self._listen_task = None
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            try:
                await self.reader.stop()
            except Exception:
                log.exception("Error stopping Live Captions reader")
            self.transcript_log.finish()
            try:
                await asyncio.to_thread(self.overlay.hide)
            except Exception:
                log.exception("Could not hide the desktop caption overlay")
            try:
                await asyncio.to_thread(force_restore_all)
            except Exception:
                log.exception("Could not restore the system Live Captions bar")
            self._publish(self.snapshot())
            return self.snapshot()

    async def _pump(self) -> None:
        try:
            async for line in self.reader.lines():
                view = self.buffer.ingest(line.text)
                self._apply(line.text, view)
                self.transcript_log.update(view.full)
                self._publish(self.state.caption_event())
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self.state.running = False
            self.state.error = self._format(exc)
            self.transcript_log.finish()
            self._publish(self.snapshot())
            log.exception("Caption pump failed")

    def _apply(self, live: str, view: TranscriptView) -> None:
        self.state.live = live
        self.state.committed = view.committed
        self.state.provisional = view.provisional
        self.state.full = view.full

    def _publish(self, event: dict) -> None:
        if event.get("type") != "inject":
            try:
                self.overlay.update(event)
            except Exception:
                log.exception("Could not update the desktop caption overlay")
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                log.exception("Caption listener failed")

    @staticmethod
    def _format(exc: BaseException) -> str:
        if isinstance(exc, LiveFeedError):
            return exc.display()
        return str(exc)
