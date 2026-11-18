"""Compact always-on-top caption panel: content plus a side strip with close, move and resize."""

from __future__ import annotations

import logging
import queue
import sys
import threading
import tkinter as tk
from ctypes import windll, wintypes

from livefeed.settings import (
    MAX_HEIGHT,
    MAX_WIDTH,
    MIN_HEIGHT,
    MIN_WIDTH,
    OverlayPrefs,
    load_overlay_prefs,
    save_overlay_prefs,
    update_overlay_prefs,
)

log = logging.getLogger("livefeed.overlay")

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
GA_ROOT = 2
BG = "#111820"
FG = "#eef3f8"
MUTED = "#8ea0b3"
ACCENT = "#7de3d4"
MARK_BG = "#2f4a36"
MARK_FG = "#d7e08a"
STRIP_BG = "#0b1117"
MOVE_BG = "#2563eb"
MOVE_HOVER = "#3b82f6"
MOVE_FG = "#ffffff"
STRIP_WIDTH = 48


def _hwnd(root: tk.Misc) -> int:
    hwnd = int(root.winfo_id())
    if sys.platform != "win32":
        return hwnd
    ancestor = int(windll.user32.GetAncestor(hwnd, GA_ROOT) or 0)
    return ancestor or hwnd


def _pin_topmost(hwnd: int) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    user32 = windll.user32
    user32.SetWindowPos(
        wintypes.HWND(hwnd),
        wintypes.HWND(HWND_TOPMOST),
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd,
        GWL_EXSTYLE,
        style | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
    )


class _OverlayWindow:
    def __init__(self, root: tk.Tk, on_visibility, on_inject) -> None:
        self.root = root
        self.on_visibility = on_visibility
        self.on_inject = on_inject
        self.prefs = load_overlay_prefs()
        self._drag = {"x": 0, "y": 0}
        self._resize = {"x": 0, "y": 0, "w": 0, "h": 0}
        self._sel_start: int | None = None
        self._sel_end: int | None = None
        self._sel_text = ""
        self._build()
        self._apply_style()
        self._place(size=True, position=True)

    def _build(self) -> None:
        root = self.root
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=BG)

        # Controls live in their own strip so the move handle can be large
        # without covering caption text.
        self.strip = tk.Frame(root, bg=STRIP_BG, width=STRIP_WIDTH)
        self.strip.pack(side="right", fill="y")
        self.strip.pack_propagate(False)

        self.body = tk.Text(
            root,
            bg=BG,
            fg=FG,
            insertbackground=BG,
            insertwidth=0,
            bd=0,
            highlightthickness=0,
            wrap="word",
            font=("Segoe UI", self.prefs.font_size),
            padx=16,
            pady=12,
            cursor="xterm",
            exportselection=False,
        )
        self.body.pack(fill="both", expand=True)
        self.body.tag_configure("committed", foreground=FG)
        self.body.tag_configure("provisional", foreground=ACCENT)
        self.body.tag_configure("empty", foreground=MUTED)
        self.body.tag_configure("mark", background=MARK_BG, foreground=MARK_FG)
        self.body.configure(selectbackground=MARK_BG, selectforeground=MARK_FG)
        self.body.tag_raise("mark")

        self.close = tk.Button(
            self.strip,
            text="×",
            command=self.hide,
            bd=0,
            fg=FG,
            bg=STRIP_BG,
            activebackground="#243040",
            activeforeground=FG,
            font=("Segoe UI", 14),
            cursor="hand2",
        )
        self.close.pack(side="top", fill="x", padx=4, pady=(4, 2))

        self.grip = tk.Label(
            self.strip, text="◢", fg=MUTED, bg=STRIP_BG, cursor="size_nw_se", font=("Segoe UI", 12)
        )
        self.grip.pack(side="bottom", fill="x", padx=4, pady=(2, 2))

        self.move = tk.Label(
            self.strip,
            text="✥",
            fg=MOVE_FG,
            bg=MOVE_BG,
            font=("Segoe UI", 22, "bold"),
            cursor="fleur",
        )
        self.move.pack(side="top", fill="both", expand=True, padx=4, pady=2)
        self.move.bind("<Enter>", lambda _e: self.move.configure(bg=MOVE_HOVER))
        self.move.bind("<Leave>", lambda _e: self.move.configure(bg=MOVE_BG))

        self.body.bind("<Key>", self._block_edit)
        self.body.bind("<<Paste>>", lambda _e: "break")
        self.body.bind("<<Cut>>", lambda _e: "break")
        self.body.bind("<ButtonRelease-1>", self._capture_selection)
        self.body.bind("<Double-Button-1>", self._after_select)
        self.body.bind("<B1-Motion>", self._after_select)
        self.body.bind("<Button-3>", self._on_right)
        root.bind("<Button-3>", self._on_right)
        self.move.bind("<Button-1>", self._start_drag)
        self.move.bind("<B1-Motion>", self._on_drag)
        self.move.bind("<ButtonRelease-1>", lambda _e: self._persist_position())
        self.grip.bind("<Button-1>", self._start_resize)
        self.grip.bind("<B1-Motion>", self._on_resize)
        self.grip.bind("<ButtonRelease-1>", lambda _e: self._persist_size())

    def show(self) -> None:
        self.prefs = load_overlay_prefs()
        self._apply_style()
        self._place(size=True, position=True)
        self.root.deiconify()
        self.pin()
        self.on_visibility(True)

    def hide(self) -> None:
        self.root.withdraw()
        self.on_visibility(False)

    def pin(self) -> None:
        self.root.update_idletasks()
        _pin_topmost(_hwnd(self.root))

    def paint(self, event: dict | None) -> None:
        committed = ((event or {}).get("committed") or "").strip()
        provisional = ((event or {}).get("provisional") or "").strip()
        full = ((event or {}).get("full") or (event or {}).get("live") or "").strip()
        self.body.delete("1.0", "end")
        if not full:
            self.body.insert("1.0", "Waiting for Windows Live Captions…", "empty")
        else:
            if committed:
                self.body.insert("end", committed + " ", "committed")
            self.body.insert("end", provisional or (full if not committed else ""), "provisional")
        self.body.see("end")
        self._restore_mark()

    def apply_changes(self, changes: dict) -> None:
        self.prefs = update_overlay_prefs(**changes)
        self._apply_style()
        if any(key in changes for key in ("width", "height")):
            self._place(size=True)
        if any(key in changes for key in ("x", "y")):
            self._place(position=True)

    def _apply_style(self) -> None:
        self.prefs.clamp()
        try:
            self.root.attributes("-alpha", self.prefs.opacity)
        except tk.TclError:
            pass
        self.body.configure(font=("Segoe UI", self.prefs.font_size))
        self.pin()

    def _place(self, *, size: bool = False, position: bool = False) -> None:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(max(self.prefs.width, MIN_WIDTH), min(MAX_WIDTH, screen_w - 16))
        height = min(max(self.prefs.height, MIN_HEIGHT), min(MAX_HEIGHT, screen_h - 16))
        if self.prefs.x is None or self.prefs.y is None:
            self.prefs.x = max(16, (screen_w - width) // 2)
            self.prefs.y = max(16, screen_h - height - 48)
            save_overlay_prefs(self.prefs)
            size = True
            position = True
        if not size and not position:
            return
        x = int(self.prefs.x)
        y = int(self.prefs.y)
        if size:
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        else:
            self.root.geometry(f"+{x}+{y}")
        self.pin()

    def _block_edit(self, event: tk.Event) -> str | None:
        if event.state & 0x4 and event.keysym.lower() in {"c"}:
            return None
        return "break"

    def _after_select(self, _event: tk.Event | None = None) -> None:
        self.root.after_idle(self._capture_selection)

    def _char_count(self, start: str, end: str) -> int:
        counted = self.body.count(start, end, "chars")
        if not counted:
            return 0
        return int(counted[0])

    def _content(self) -> str:
        return self.body.get("1.0", "end-1c")

    def _is_placeholder(self) -> bool:
        text = self._content().strip()
        return not text or text.startswith("Waiting for")

    def _capture_selection(self, _event: tk.Event | None = None) -> None:
        if self._is_placeholder():
            return
        try:
            start = self.body.index("sel.first")
            end = self.body.index("sel.last")
        except tk.TclError:
            return
        if self.body.compare(start, "==", end):
            return
        self._sel_start = self._char_count("1.0", start)
        self._sel_end = self._char_count("1.0", end)
        self._sel_text = self.body.get(start, end)
        self._apply_mark()

    def _restore_mark(self) -> None:
        if self._sel_start is None or self._is_placeholder():
            self.body.tag_remove("mark", "1.0", "end")
            return
        content = self._content()
        snippet = self._sel_text
        if snippet:
            best = content.find(snippet)
            cursor = best
            while cursor >= 0:
                if abs(cursor - self._sel_start) < abs(best - self._sel_start):
                    best = cursor
                cursor = content.find(snippet, cursor + 1)
            if best >= 0:
                self._sel_start = best
                self._sel_end = best + len(snippet)
        self._apply_mark()

    def _apply_mark(self) -> None:
        self.body.tag_remove("mark", "1.0", "end")
        if self._sel_start is None or self._sel_end is None:
            return
        total = self._char_count("1.0", "end-1c")
        start = max(0, min(self._sel_start, total))
        end = max(start, min(self._sel_end, total))
        if end <= start:
            return
        self.body.tag_add("mark", f"1.0+{start}c", f"1.0+{end}c")
        self.body.tag_raise("mark")

    def _on_right(self, _event: tk.Event) -> str:
        if self._sel_start is None or self._is_placeholder():
            return "break"
        total = self._char_count("1.0", "end-1c")
        start = max(0, min(self._sel_start, total))
        text = self.body.get(f"1.0+{start}c", "end-1c").strip()
        if not text:
            return "break"
        if self.on_inject:
            self.on_inject(text)
        self._flash()
        return "break"

    def _flash(self) -> None:
        self.body.configure(bg="#1c3a36")
        self.root.after(180, lambda: self.body.configure(bg=BG))

    def _start_drag(self, event: tk.Event) -> None:
        self._drag["x"] = event.x_root - int(self.prefs.x if self.prefs.x is not None else self.root.winfo_x())
        self._drag["y"] = event.y_root - int(self.prefs.y if self.prefs.y is not None else self.root.winfo_y())

    def _on_drag(self, event: tk.Event) -> None:
        self.prefs.x = event.x_root - self._drag["x"]
        self.prefs.y = event.y_root - self._drag["y"]
        self.root.geometry(f"+{self.prefs.x}+{self.prefs.y}")

    def _persist_position(self) -> None:
        save_overlay_prefs(self.prefs)

    def _start_resize(self, event: tk.Event) -> None:
        self._resize = {
            "x": event.x_root,
            "y": event.y_root,
            "w": self.prefs.width,
            "h": self.prefs.height,
        }

    def _on_resize(self, event: tk.Event) -> None:
        width = max(MIN_WIDTH, min(MAX_WIDTH, self._resize["w"] + (event.x_root - self._resize["x"])))
        height = max(MIN_HEIGHT, min(MAX_HEIGHT, self._resize["h"] + (event.y_root - self._resize["y"])))
        self.prefs.width = width
        self.prefs.height = height
        self._place(size=True)

    def _persist_size(self) -> None:
        save_overlay_prefs(self.prefs)


class CaptionOverlay:
    def __init__(self) -> None:
        self.on_inject = None
        self._commands: queue.Queue[tuple[str, dict | None]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._visible = False
        self._lock = threading.Lock()

    @property
    def visible(self) -> bool:
        return self._visible

    def show(self) -> None:
        self._set_visible(True)
        self._ensure()
        self._commands.put(("show", None))

    def hide(self) -> None:
        self._set_visible(False)
        self._commands.put(("hide", None))

    def update(self, event: dict) -> None:
        self._commands.put(("text", event))

    def set_prefs(self, **changes) -> None:
        update_overlay_prefs(**changes)
        self._commands.put(("prefs", changes))

    def close(self) -> None:
        self._set_visible(False)
        self._commands.put(("quit", None))

    def _set_visible(self, value: bool) -> None:
        with self._lock:
            self._visible = value

    def _ensure(self) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="livefeed-overlay", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)

    def _run(self) -> None:
        root = tk.Tk()
        window = _OverlayWindow(
            root,
            self._set_visible,
            lambda text: self.on_inject and self.on_inject(text),
        )
        window.hide()

        def pump() -> None:
            shown = self.visible
            while True:
                try:
                    kind, payload = self._commands.get_nowait()
                except queue.Empty:
                    break
                if kind == "show":
                    window.show()
                    shown = True
                elif kind == "hide":
                    window.hide()
                    shown = False
                elif kind == "text":
                    window.paint(payload)
                elif kind == "prefs" and payload:
                    window.apply_changes(payload)
                elif kind == "quit":
                    window.hide()
                    root.quit()
                    return
            if shown:
                window.pin()
            root.after(80, pump)

        window.paint(None)
        self._ready.set()
        root.after(80, pump)
        try:
            root.mainloop()
        except Exception:
            log.exception("Caption overlay closed unexpectedly")
        finally:
            self._ready.clear()
