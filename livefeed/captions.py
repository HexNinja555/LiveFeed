"""Read Windows 11 Live Captions through UI Automation.

This is the same attachment flow HelpME uses: launch LiveCaptions.exe if needed,
find the desktop caption window, then pull text from known caption controls
(or walk the automation tree). The bar can be cloaked after attach. Nothing
is OCR'd and no audio is recorded.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from livefeed.errors import CaptionError

WINDOW_CLASS = "LiveCaptionsDesktopWindow"
WINDOW_NAME = "Live Captions"
CAPTION_IDS = ("CaptionsTextBlock", "CaptionTextBlock", "CaptionText")
SKIP_IDS = frozenset(
    {
        "ReadyToCaptionTextBlock",
        "SelectionReadyToCaptionTextBlock",
        "SettingUpLiveCaptionsTextBlock",
        "CaptionIconTextBlock",
        "CaptionOnlyTitleTextBlock",
        "CaptionOnlyInfoTextBlock",
        "SettingsButton",
        "CloseButton",
        "MicrophoneErrorTip",
        "SpeechRecognitionLatencyTip",
        "PrivacyTeachingTip",
    }
)
SKIP_NAME_PREFIXES = (
    "ready to show live captions",
    "setting up live captions",
    "live captions needs",
    "close live captions",
    "include microphone",
    "position live captions",
)
CHROME_NAMES = frozenset({"settings", "live captions", "close"})

# UIAutomationCore property / control / pattern ids.
UIA_PROCESS_ID = 30002
UIA_VALUE = 30045
UIA_LEGACY_NAME = 30092
UIA_TEXT_PATTERN = 10014
UIA_EDIT = 50004
UIA_TEXT = 50020
UIA_DOCUMENT = 50030
SCOPE_CHILDREN = 2
SCOPE_DESCENDANTS = 4
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def captions_exe() -> Path:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    return windir / "System32" / "LiveCaptions.exe"


def caption_process_ids() -> list[int]:
    try:
        import psutil
    except Exception:
        return []
    found: list[int] = []
    for proc in psutil.process_iter(["name", "pid"]):
        name = (proc.info.get("name") or "").lower()
        if name == "livecaptions.exe":
            found.append(int(proc.info["pid"]))
    return found


def captions_are_running() -> bool:
    return bool(caption_process_ids())


def launch_live_captions() -> None:
    if sys.platform != "win32":
        raise CaptionError(
            "Windows 11 Live Captions is only available on Windows.",
            detail="This capture path reads the Live Captions accessibility tree.",
        )
    exe = captions_exe()
    if not exe.is_file():
        raise CaptionError(
            "Windows Live Captions was not found.",
            detail=(
                "Install or update Windows 11, then enable "
                "Settings → Accessibility → Captions → Live captions."
            ),
        )
    if captions_are_running():
        return
    flags = CREATE_BREAKAWAY_FROM_JOB | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [str(exe)],
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )


def wait_for_caption_window(*, timeout_s: float = 12.0) -> None:
    deadline = time.monotonic() + timeout_s
    last = "window not found"
    while time.monotonic() < deadline:
        try:
            if caption_window_open():
                return
        except Exception as exc:
            last = str(exc)
        time.sleep(0.2)
    raise CaptionError(
        "Could not attach to the Windows Live Captions window.",
        detail=last + "\nPress Win+Ctrl+L, then start capture again.",
    )


def read_caption_text() -> str:
    """One-shot read of the current caption line, or empty if idle."""
    return _read_once() or ""


def bind_uia():
    return _bind_uia()


def unbind_uia() -> None:
    _unbind_uia()


def locate_window(automation, uia):
    return _locate_window(automation, uia)


def element_alive(element) -> bool:
    return _alive(element)


def caption_window_open() -> bool:
    automation, uia = bind_uia()
    try:
        return locate_window(automation, uia) is not None
    finally:
        unbind_uia()


def is_ui_chrome(name: str) -> bool:
    lowered = name.strip().casefold()
    if not lowered or lowered in CHROME_NAMES:
        return True
    return any(lowered.startswith(prefix) for prefix in SKIP_NAME_PREFIXES)


def clean_caption(raw: str) -> str:
    kept: list[str] = []
    for line in (raw or "").replace("\xa0", " ").splitlines():
        collapsed = " ".join(line.split())
        if collapsed and not is_ui_chrome(collapsed):
            kept.append(collapsed)
    return " ".join(kept)


def _alive(element) -> bool:
    if element is None:
        return False
    try:
        element.CurrentControlType
        return True
    except Exception:
        return False


def _automation_id(element) -> str:
    try:
        return str(element.CurrentAutomationId or "").strip()
    except Exception:
        return ""


def _element_text(element) -> str:
    probes = (
        lambda: element.CurrentName,
        lambda: element.GetCurrentPropertyValue(UIA_VALUE),
        lambda: element.GetCurrentPropertyValue(UIA_LEGACY_NAME),
        lambda: element.GetCurrentPattern(UIA_TEXT_PATTERN).DocumentRange.GetText(-1),
    )
    for probe in probes:
        try:
            value = str(probe() or "").strip()
        except Exception:
            continue
        cleaned = clean_caption(value)
        if cleaned:
            return cleaned
    return ""


def _read_once() -> str:
    automation, uia = _bind_uia()
    try:
        window = _locate_window(automation, uia)
        if not _alive(window):
            return ""
        return extract_caption(automation, uia, window)
    finally:
        _unbind_uia()


def _bind_uia():
    import comtypes
    import comtypes.client

    comtypes.CoInitialize()
    uia = comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation

    automation = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
    return automation, uia


def _unbind_uia() -> None:
    import comtypes

    try:
        comtypes.CoUninitialize()
    except Exception:
        pass


def _first_match(automation, root, property_id, value, scope):
    try:
        condition = automation.CreatePropertyCondition(property_id, value)
        element = root.FindFirst(scope, condition)
    except Exception:
        return None
    return element if _alive(element) else None


def _locate_window(automation, uia):
    try:
        desktop = automation.GetRootElement()
    except Exception:
        return None
    window = _first_match(
        automation, desktop, uia.UIA_ClassNamePropertyId, WINDOW_CLASS, SCOPE_CHILDREN
    )
    if window is not None:
        return window
    window = _first_match(
        automation, desktop, uia.UIA_NamePropertyId, WINDOW_NAME, SCOPE_CHILDREN
    )
    if window is not None:
        return window
    for pid in caption_process_ids():
        window = _first_match(automation, desktop, UIA_PROCESS_ID, int(pid), SCOPE_CHILDREN)
        if window is not None:
            return window
    return _first_match(
        automation, desktop, uia.UIA_ClassNamePropertyId, WINDOW_CLASS, SCOPE_DESCENDANTS
    )


def extract_caption(automation, uia, window) -> str:
    for aid in CAPTION_IDS:
        element = _first_match(
            automation, window, uia.UIA_AutomationIdPropertyId, aid, SCOPE_DESCENDANTS
        )
        if element is None:
            continue
        text = _element_text(element)
        if text:
            return text
    return _walk_caption_text(automation, window)


def _walk_caption_text(automation, window) -> str:
    seen: set[str] = set()
    pieces: list[str] = []
    walker = automation.CreateTreeWalker(automation.RawViewCondition)

    def add(text: str) -> None:
        if not text:
            return
        key = text.casefold()
        if key in seen:
            return
        seen.add(key)
        pieces.append(text)

    def walk(element, depth: int) -> None:
        if not _alive(element) or depth > 24:
            return
        if _automation_id(element) in SKIP_IDS:
            return
        try:
            control = int(element.CurrentControlType)
        except Exception:
            control = 0
        if control in {UIA_TEXT, UIA_DOCUMENT, UIA_EDIT}:
            add(_element_text(element))
        try:
            child = walker.GetFirstChildElement(element)
        except Exception:
            return
        while _alive(child):
            walk(child, depth + 1)
            try:
                sibling = walker.GetNextSiblingElement(child)
            except Exception:
                break
            child = sibling

    walk(window, 0)
    return " ".join(pieces)
