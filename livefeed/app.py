"""Desktop LiveFeed app: Start/Stop capture and keep the extension in sync."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
import threading
import urllib.error
import urllib.request
from ctypes import windll
import tkinter as tk
from tkinter import ttk

import psutil

from livefeed.hub import CaptionHub
from livefeed.server import DEFAULT_HOST, DEFAULT_PORT, start_http
from livefeed.settings import MAX_FONT, MAX_OPACITY, MIN_FONT, MIN_OPACITY, load_overlay_prefs
from livefeed.window import force_restore_all

log = logging.getLogger("livefeed.app")

WINDOW_TITLE = "LiveFeed"
_MUTEX_NAME = "Local\\LiveFeed.Desktop.1"
_MUTEX_HANDLE = None
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9


def _focus_existing() -> bool:
    if sys.platform != "win32":
        return False
    hwnd = int(windll.user32.FindWindowW(None, WINDOW_TITLE) or 0)
    if not hwnd:
        return False
    user32 = windll.user32
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    return True


def _claim_instance() -> bool:
    global _MUTEX_HANDLE
    if sys.platform != "win32":
        return True
    _MUTEX_HANDLE = windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    return int(windll.kernel32.GetLastError()) != ERROR_ALREADY_EXISTS


def _port_free(host: str, port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _port_held_by_livefeed(host: str, port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/status", timeout=0.6) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return False
    return isinstance(data, dict) and "extension_connected" in data


def _other_livefeed_processes() -> list[psutil.Process]:
    mine = os.getpid()
    found: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        if proc.info["pid"] == mine:
            continue
        name = (proc.info.get("name") or "").lower()
        cmd = " ".join(proc.info.get("cmdline") or []).lower()
        if "livefeed" not in cmd:
            continue
        if not any(token in name for token in ("python", "py.exe", "pyw.exe")):
            continue
        try:
            found.append(psutil.Process(proc.info["pid"]))
        except psutil.Error:
            continue
    return found


def _stop_other_livefeed() -> None:
    procs = _other_livefeed_processes()
    for proc in procs:
        try:
            proc.terminate()
        except psutil.Error:
            continue
    _, alive = psutil.wait_procs(procs, timeout=2.5)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            continue


class LiveFeedApp:
    def __init__(self, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self.hub = CaptionHub()
        self.loop = asyncio.new_event_loop()
        self.runner = None
        self._busy = False
        self._thread = threading.Thread(target=self._run_async, name="livefeed-io", daemon=True)

        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.configure(bg="#11161c")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        card = tk.Frame(self.root, bg="#11161c", padx=18, pady=16)
        card.pack(fill="both", expand=True)
        tk.Label(
            card,
            text="LiveFeed",
            fg="#e8eef6",
            bg="#11161c",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            card,
            text="Start capture here. The extension connects automatically.",
            fg="#93a0b0",
            bg="#11161c",
            font=("Segoe UI", 9),
            wraplength=340,
            justify="left",
        ).pack(anchor="w", pady=(2, 12))

        self.status = tk.Label(
            card,
            text="Starting local service…",
            fg="#d7e08a",
            bg="#11161c",
            font=("Segoe UI", 10, "bold"),
        )
        self.status.pack(anchor="w")
        self.extension = tk.Label(
            card,
            text="Extension: waiting",
            fg="#93a0b0",
            bg="#11161c",
            font=("Segoe UI", 9),
        )
        self.extension.pack(anchor="w", pady=(2, 12))
        self.detail = tk.Label(
            card,
            text="",
            fg="#ff8a80",
            bg="#11161c",
            font=("Segoe UI", 8),
            wraplength=340,
            justify="left",
        )
        self.detail.pack(anchor="w")

        prefs = load_overlay_prefs()
        look = tk.LabelFrame(
            card,
            text="Caption bar",
            fg="#93a0b0",
            bg="#11161c",
            font=("Segoe UI", 8),
            padx=8,
            pady=6,
        )
        look.pack(fill="x", pady=(10, 0))
        self.font_var = tk.IntVar(value=prefs.font_size)
        self.opacity_var = tk.DoubleVar(value=prefs.opacity)
        self._pref_scale(look, "Font size", self.font_var, MIN_FONT, MAX_FONT, 1, self._apply_caption_prefs)
        self._pref_scale(look, "Opacity", self.opacity_var, MIN_OPACITY, MAX_OPACITY, 0.01, self._apply_caption_prefs)

        actions = tk.Frame(card, bg="#11161c")
        actions.pack(fill="x", pady=(14, 0))
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Start.TButton", padding=8, font=("Segoe UI", 10, "bold"))
        style.configure("Stop.TButton", padding=8, font=("Segoe UI", 10))
        self.start_btn = ttk.Button(actions, text="Start", style="Start.TButton", command=self._on_start)
        self.stop_btn = ttk.Button(actions, text="Stop", style="Stop.TButton", command=self._on_stop)
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.stop_btn.pack(side="left", fill="x", expand=True)

        view = tk.Frame(card, bg="#11161c")
        view.pack(fill="x", pady=(8, 0))
        style.configure("View.TButton", padding=6, font=("Segoe UI", 9))
        self.show_btn = ttk.Button(view, text="Show captions", style="View.TButton", command=self._show_overlay)
        self.hide_btn = ttk.Button(view, text="Hide captions", style="View.TButton", command=self._hide_overlay)
        self.show_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.hide_btn.pack(side="left", fill="x", expand=True)

    def run(self) -> None:
        self._thread.start()
        self.root.after(250, self._refresh)
        self.root.mainloop()

    def _run_async(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.create_task(self._boot())
        self.loop.run_forever()

    async def _boot(self) -> None:
        self.hub.bind_loop(self.loop)
        try:
            self.runner = await start_http(self.hub, self.host, self.port)
        except Exception:
            log.exception("Could not start the LiveFeed service")
            if _focus_existing() or _port_held_by_livefeed(self.host, self.port):
                self.root.after(0, self.root.destroy)
                return
            self.hub.state.error = (
                f"Could not listen on {self.host}:{self.port}. "
                "LiveFeed is already running — use that window, or close it first."
            )
            self._publish()

    def _submit(self, coro):
        if not self.loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _pref_scale(self, parent, label, variable, start, end, resolution, command) -> None:
        row = tk.Frame(parent, bg="#11161c")
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, fg="#93a0b0", bg="#11161c", width=10, anchor="w").pack(side="left")
        tk.Scale(
            row,
            from_=start,
            to=end,
            resolution=resolution,
            orient="horizontal",
            showvalue=False,
            variable=variable,
            command=lambda _v: command(),
            bg="#11161c",
            fg="#e8eef6",
            troughcolor="#2a3542",
            highlightthickness=0,
            sliderrelief="flat",
            length=180,
        ).pack(side="left", fill="x", expand=True)

    def _apply_caption_prefs(self) -> None:
        self.hub.overlay.set_prefs(
            font_size=int(self.font_var.get()),
            opacity=float(self.opacity_var.get()),
        )

    def _show_overlay(self) -> None:
        self.hub.overlay.show()

    def _hide_overlay(self) -> None:
        self.hub.overlay.hide()

    def _on_start(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._submit(self._start())

    def _on_stop(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._submit(self._stop())

    async def _start(self) -> None:
        try:
            await self.hub.start()
        except Exception as exc:
            self.hub.state.error = self.hub._format(exc)
            force_restore_all()
            self._publish()
        finally:
            self._busy = False

    async def _stop(self) -> None:
        try:
            await self.hub.stop()
        finally:
            force_restore_all()
            self._busy = False
            self._publish()

    async def _shutdown(self) -> None:
        try:
            await self.hub.stop()
        finally:
            force_restore_all()
            try:
                self.hub.overlay.close()
            except Exception:
                log.exception("Could not close the caption overlay")
            if self.runner is not None:
                await self.runner.cleanup()
                self.runner = None
            self.loop.call_soon_threadsafe(self.loop.stop)

    def _on_close(self) -> None:
        try:
            if self.loop.is_running():
                future = asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop)
                try:
                    future.result(timeout=5)
                except Exception:
                    force_restore_all()
            else:
                force_restore_all()
            try:
                self.hub.overlay.close()
            except Exception:
                pass
            _stop_other_livefeed()
            try:
                self.root.destroy()
            except Exception:
                pass
        finally:
            os._exit(0)

    def _publish(self) -> None:
        try:
            self.hub._publish(self.hub.snapshot())
        except Exception:
            pass

    def _refresh(self) -> None:
        state = self.hub.snapshot()
        if state["running"]:
            self.status.configure(text="Capturing", fg="#3dd6c6")
        elif state["starting"]:
            self.status.configure(text="Starting…", fg="#d7e08a")
        else:
            self.status.configure(text="Stopped", fg="#c2ccd8")
        if state.get("extension_connected"):
            count = int(state.get("extension_clients") or 0)
            self.extension.configure(
                text=f"Extension: connected ({count})",
                fg="#3dd6c6",
            )
        else:
            self.extension.configure(text="Extension: not connected", fg="#93a0b0")
        self.detail.configure(text=state.get("error") or "")
        self.start_btn.configure(state="disabled" if state["running"] or state["starting"] or self._busy else "normal")
        self.stop_btn.configure(state="normal" if state["running"] or state["starting"] else "disabled")
        shown = self.hub.overlay.visible
        self.show_btn.configure(state="disabled" if shown else "normal")
        self.hide_btn.configure(state="normal" if shown else "disabled")
        self.root.after(300, self._refresh)


def run_app(*, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> int:
    if _focus_existing() and not _port_free(host, port):
        return 0
    if not _port_free(host, port) or _other_livefeed_processes():
        _stop_other_livefeed()
    _claim_instance()
    LiveFeedApp(host=host, port=port).run()
    return 0
