"""Keep the Live Captions process running while hiding its desktop bar.

UI Automation needs the window to exist. SW_HIDE often drops it from the
accessibility tree or pauses recognition, so the default hide is DWM cloak
plus full transparency and an off-screen move. The HWND stays shown.
"""

from __future__ import annotations

import logging
import sys
import threading
from ctypes import WINFUNCTYPE, byref, c_int, c_void_p, create_unicode_buffer, sizeof, windll, wintypes
from dataclasses import dataclass

from livefeed.captions import WINDOW_CLASS, WINDOW_NAME, caption_process_ids

log = logging.getLogger("livefeed.window")

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
LWA_ALPHA = 0x00000002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWNA = 8
SW_RESTORE = 9
HWND_BOTTOM = 1
HWND_TOPMOST = -1
DWMWA_CLOAK = 13
SM_CXSCREEN = 0
SM_CYSCREEN = 1
DEFAULT_BAR_W = 720
DEFAULT_BAR_H = 120
OFFSCREEN = (-32000, -32000)
_LAST_VISIBLE: dict[int, WindowSnapshot] = {}

if sys.platform == "win32":
    _user32 = windll.user32
    _dwmapi = windll.dwmapi
    _user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindow.restype = wintypes.BOOL
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, wintypes.LPDWORD]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, c_int]
    _user32.GetWindowLongW.restype = wintypes.LONG
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, c_int, wintypes.LONG]
    _user32.SetWindowLongW.restype = wintypes.LONG
    _user32.GetWindowRect.argtypes = [wintypes.HWND, wintypes.LPRECT]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        c_int,
        c_int,
        c_int,
        c_int,
        wintypes.UINT,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.SetLayeredWindowAttributes.argtypes = [
        wintypes.HWND,
        wintypes.COLORREF,
        wintypes.BYTE,
        wintypes.DWORD,
    ]
    _user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
    _user32.ShowWindow.argtypes = [wintypes.HWND, c_int]
    _user32.ShowWindow.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.GetSystemMetrics.argtypes = [c_int]
    _user32.GetSystemMetrics.restype = c_int
    _EnumWindowsProc = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows.argtypes = [_EnumWindowsProc, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, c_int]
    _user32.GetClassNameW.restype = c_int
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, c_int]
    _user32.GetWindowTextW.restype = c_int
    _dwmapi.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        c_void_p,
        wintypes.DWORD,
    ]
    _dwmapi.DwmSetWindowAttribute.restype = wintypes.LONG
else:
    _user32 = None
    _dwmapi = None
    _EnumWindowsProc = None


@dataclass
class WindowSnapshot:
    hwnd: int
    left: int
    top: int
    width: int
    height: int
    exstyle: int
    visible: bool


def caption_hwnds() -> list[int]:
    if sys.platform != "win32" or _user32 is None:
        return []
    found: list[int] = []

    def consider(hwnd: int) -> None:
        if not hwnd or hwnd in found or not _user32.IsWindow(hwnd):
            return
        found.append(int(hwnd))

    consider(_user32.FindWindowW(WINDOW_CLASS, None))
    consider(_user32.FindWindowW(None, WINDOW_NAME))

    pids = set(caption_process_ids())
    name_buf = create_unicode_buffer(256)
    title_buf = create_unicode_buffer(256)

    def callback(hwnd, _lparam):
        _user32.GetClassNameW(hwnd, name_buf, 256)
        klass = name_buf.value
        _user32.GetWindowTextW(hwnd, title_buf, 256)
        title = title_buf.value
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, byref(pid))
        if klass == WINDOW_CLASS or title == WINDOW_NAME or int(pid.value) in pids:
            if klass == WINDOW_CLASS or title == WINDOW_NAME:
                consider(int(hwnd))
        return True

    _user32.EnumWindows(_EnumWindowsProc(callback), 0)
    return found


def _on_screen(snap: WindowSnapshot) -> bool:
    return snap.left > -10000 and snap.top > -10000 and snap.width > 8 and snap.height > 8


def remember_placement(hwnd: int) -> WindowSnapshot:
    snap = snapshot_window(hwnd)
    if _on_screen(snap):
        _LAST_VISIBLE[hwnd] = snap
        return snap
    return _LAST_VISIBLE.get(hwnd, snap)


def snapshot_window(hwnd: int) -> WindowSnapshot:
    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, byref(rect))
    return WindowSnapshot(
        hwnd=int(hwnd),
        left=int(rect.left),
        top=int(rect.top),
        width=int(rect.right - rect.left),
        height=int(rect.bottom - rect.top),
        exstyle=int(_user32.GetWindowLongW(hwnd, GWL_EXSTYLE)),
        visible=bool(_user32.IsWindowVisible(hwnd)),
    )


def _cloak(hwnd: int, hidden: bool) -> None:
    if _dwmapi is None:
        return
    value = c_int(1 if hidden else 0)
    _dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CLOAK, byref(value), sizeof(value))


def apply_hide(hwnd: int, method: str) -> None:
    if sys.platform != "win32" or not hwnd or not _user32.IsWindow(hwnd):
        return
    method = (method or "cloak").strip().lower()
    if method == "hide":
        _user32.ShowWindow(hwnd, SW_HIDE)
        return
    if method in {"cloak", "transparent", "offscreen"}:
        exstyle = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(
            hwnd,
            GWL_EXSTYLE,
            exstyle | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT,
        )
        if method in {"cloak", "transparent"}:
            _user32.SetLayeredWindowAttributes(hwnd, 0, 0, LWA_ALPHA)
        if method in {"cloak", "offscreen"}:
            _user32.SetWindowPos(
                hwnd,
                HWND_BOTTOM,
                OFFSCREEN[0],
                OFFSCREEN[1],
                0,
                0,
                SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
        if method == "cloak":
            _cloak(hwnd, True)
        _user32.ShowWindow(hwnd, SW_SHOWNA)


def default_bar_rect() -> tuple[int, int, int, int]:
    if sys.platform != "win32" or _user32 is None:
        return (80, 40, DEFAULT_BAR_W, DEFAULT_BAR_H)
    screen_w = int(_user32.GetSystemMetrics(SM_CXSCREEN) or 1280)
    width = min(DEFAULT_BAR_W, max(420, screen_w - 80))
    height = DEFAULT_BAR_H
    left = max(16, (screen_w - width) // 2)
    top = 40
    return left, top, width, height


def _visible_rect(snap: WindowSnapshot | None) -> tuple[int, int, int, int]:
    if snap is not None and _on_screen(snap):
        return snap.left, snap.top, max(snap.width, 320), max(snap.height, 72)
    return default_bar_rect()


def restore_window(hwnd: int, snap: WindowSnapshot | None = None) -> None:
    """Put one Live Captions window back on screen with normal visibility."""
    if sys.platform != "win32" or not hwnd or not _user32.IsWindow(hwnd):
        return
    _cloak(hwnd, False)
    left, top, width, height = _visible_rect(snap)
    exstyle = snap.exstyle if snap is not None else int(_user32.GetWindowLongW(hwnd, GWL_EXSTYLE))
    exstyle &= ~WS_EX_TRANSPARENT
    exstyle &= ~WS_EX_NOACTIVATE
    if exstyle & WS_EX_LAYERED:
        _user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
    _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle)
    _user32.ShowWindow(hwnd, SW_RESTORE)
    _user32.SetWindowPos(
        hwnd,
        HWND_TOPMOST,
        left,
        top,
        width,
        height,
        SWP_SHOWWINDOW | SWP_FRAMECHANGED,
    )
    _user32.ShowWindow(hwnd, SW_SHOWNORMAL)


def force_restore_all() -> int:
    """Recover every Live Captions bar, even if LiveFeed lost the original placement."""
    restored = 0
    for hwnd in caption_hwnds():
        try:
            restore_window(hwnd, _LAST_VISIBLE.get(hwnd))
            restored += 1
        except Exception:
            log.exception("Could not restore Live Captions window %s", hwnd)
    if restored:
        log.info("Forced Live Captions back on screen (%s window(s))", restored)
    return restored


class CaptionBarHider:
    """Hide the system bar after attach; restore the original placement on stop."""

    def __init__(self, *, method: str = "cloak") -> None:
        self.method = method
        self._original: dict[int, WindowSnapshot] = {}
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return bool(self._original)

    def hide(self) -> None:
        if sys.platform != "win32":
            return
        with self._lock:
            for hwnd in caption_hwnds():
                if hwnd not in self._original:
                    self._original[hwnd] = remember_placement(hwnd)
                apply_hide(hwnd, self.method)
            if self._original:
                log.info("Hid the Live Captions bar with method=%s", self.method)

    def maintain(self) -> None:
        with self._lock:
            if not self._original:
                return
            current = set(caption_hwnds())
            for hwnd in current:
                if hwnd not in self._original:
                    self._original[hwnd] = remember_placement(hwnd)
                apply_hide(hwnd, self.method)

    def forget(self) -> None:
        with self._lock:
            self._original.clear()

    def restore(self) -> None:
        with self._lock:
            originals = dict(self._original)
            self._original.clear()
        for hwnd, snap in originals.items():
            try:
                restore_window(hwnd, snap)
            except Exception:
                log.exception("Could not restore Live Captions window %s", hwnd)
        extra = force_restore_all()
        if originals or extra:
            log.info("Restored the Live Captions bar")
