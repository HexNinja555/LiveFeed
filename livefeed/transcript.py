"""Turn the rolling Live Captions window into a growing session transcript.

The OS bar repeats and rewrites a short visible slice. Blind concatenation
duplicates speech; this merge keeps overlap, treats a cleared bar as a pause,
and collapses immediate stutters.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher

_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"\S+")
_ENDED = re.compile(r"[.!?]+[\"')\]]*$")


def normalize(text: str) -> str:
    return _SPACE.sub(" ", (text or "").replace("\u00a0", " ")).strip()


def words(text: str) -> list[str]:
    return _WORD.findall(text or "")


def _key(token: str) -> str:
    return re.sub(r"[^\w+#.+-]", "", token, flags=re.UNICODE).casefold()


def _keys(tokens: list[str]) -> list[str]:
    return [_key(token) for token in tokens]


def _suffix_prefix(left: list[str], right: list[str], *, min_words: int = 3) -> int:
    if not left or not right:
        return 0
    left_n = _keys(left)
    right_n = _keys(right)
    for size in range(min(len(left_n), len(right_n)), min_words - 1, -1):
        if left_n[-size:] == right_n[:size]:
            return size
    return 0


def _drop_runs(tokens: list[str]) -> list[str]:
    out: list[str] = []
    last = None
    run = 0
    for token in tokens:
        key = _key(token)
        if key and key == last:
            run += 1
            repeated_end = bool(out and _ENDED.search(out[-1]) and _ENDED.search(token))
            if run > 1 and not repeated_end:
                continue
        else:
            run = 1
            last = key or last
        out.append(token)
    return out


def _drop_ngrams(tokens: list[str], *, smallest: int = 2) -> list[str]:
    result = list(tokens)
    changed = True
    while changed and len(result) >= smallest * 2:
        changed = False
        norm = _keys(result)
        for n in range(min(16, len(result) // 2), smallest - 1, -1):
            i = 0
            while i + 2 * n <= len(result):
                if norm[i : i + n] != norm[i + n : i + 2 * n]:
                    i += 1
                    continue
                first = result[i : i + n]
                second = result[i + n : i + 2 * n]
                if first and second and _ENDED.search(first[-1]) and _ENDED.search(second[-1]):
                    i += n
                    continue
                del result[i + n : i + 2 * n]
                changed = True
                break
            if changed:
                break
    return result


def _tidy(tokens: list[str]) -> list[str]:
    return _drop_ngrams(_drop_runs(tokens), smallest=2)


def _has_prefix(haystack: list[str], prefix: list[str]) -> bool:
    if len(haystack) < len(prefix):
        return False
    return _keys(haystack[: len(prefix)]) == _keys(prefix)


def _find_run(haystack: list[str], needle: list[str]) -> int | None:
    if not needle or len(needle) > len(haystack):
        return None
    target = _keys(needle)
    source = _keys(haystack)
    limit = len(source) - len(target) + 1
    for i in range(limit):
        if source[i : i + len(target)] == target:
            return i
    return None


def _window_covered(session_n: list[str], window_n: list[str]) -> bool:
    meaningful = [token for token in window_n if token]
    if len(meaningful) < 8:
        return False
    idx = 0
    matched = 0
    run = 0
    best = 0
    for token in meaningful:
        try:
            found = session_n.index(token, idx)
        except ValueError:
            run = 0
            continue
        idx = found + 1
        matched += 1
        run += 1
        best = max(best, run)
    return matched / len(meaningful) >= 0.8 and best >= 6


def _apply_opcodes(session: list[str], window: list[str], opcodes: list) -> list[str]:
    result: list[str] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            result.extend(window[j1:j2] or session[i1:i2])
        elif tag in {"replace", "insert"}:
            result.extend(window[j1:j2])
        elif tag == "delete":
            if i1 == 0 and i2 == len(session):
                continue
            if i1 == 0 or i2 == len(session):
                result.extend(session[i1:i2])
    return _tidy(result)


def merge_window(session: list[str], window: list[str]) -> list[str]:
    if not session:
        return list(window)
    if not window:
        return list(session)
    if _has_prefix(window, session):
        return list(window)
    if _has_prefix(session, window):
        return list(session)
    sess_n = _keys(session)
    win_n = _keys(window)
    if _find_run(session, window) is not None:
        return list(session)
    overlap = _suffix_prefix(session, window, min_words=3)
    if overlap >= 3:
        return session + window[overlap:]
    matcher = SequenceMatcher(a=sess_n, b=win_n, autojunk=False)
    if matcher.ratio() >= 0.42:
        return _apply_opcodes(session, window, matcher.get_opcodes())
    overlap = _suffix_prefix(session, window, min_words=1)
    if overlap:
        return session + window[overlap:]
    return list(session) if _window_covered(sess_n, win_n) else session + window


@dataclass(frozen=True)
class TranscriptView:
    committed: str
    provisional: str

    @property
    def full(self) -> str:
        if self.committed and self.provisional:
            return f"{self.committed} {self.provisional}"
        return self.committed or self.provisional


class TranscriptBuffer:
    def __init__(self, *, provisional_words: int = 6, pause_commit_s: float = 0.9) -> None:
        self.provisional_words = provisional_words
        self.pause_commit_s = pause_commit_s
        self._committed: list[str] = []
        self._provisional: list[str] = []
        self._last_window: list[str] = []
        self._last_event: float | None = None
        self._gap = False

    def clear(self) -> TranscriptView:
        self._committed = []
        self._provisional = []
        self._last_window = []
        self._last_event = None
        self._gap = False
        return self.view()

    def view(self) -> TranscriptView:
        return TranscriptView(
            committed=" ".join(self._committed),
            provisional=" ".join(self._provisional),
        )

    def ingest(self, raw: str, *, now: float | None = None) -> TranscriptView:
        clock = time.monotonic() if now is None else now
        text = normalize(raw)
        if not text:
            self._gap = True
            return self._on_pause(clock)

        incoming = _tidy(words(text))
        if not incoming:
            return self.view()

        after_gap = self._gap
        self._gap = False
        if after_gap and self._last_window:
            aligned = self._session() + incoming
            self._last_window = list(incoming)
            self._split(aligned)
            self._last_event = clock
            return self.view()

        if self._last_window and _keys(incoming) == _keys(self._last_window):
            if incoming != self._last_window:
                full = self._session()
                width = len(self._last_window)
                if width <= len(full) and _keys(full[-width:]) == _keys(self._last_window):
                    self._split(full[:-width] + incoming)
                    self._last_window = list(incoming)
            self._last_event = clock
            return self.view()

        aligned = _tidy(self._merge(incoming))
        self._last_window = list(incoming)
        self._split(aligned)
        self._last_event = clock
        return self.view()

    def _session(self) -> list[str]:
        return self._committed + self._provisional

    def _on_pause(self, clock: float) -> TranscriptView:
        last = self._last_event
        if last is not None and (clock - last) >= self.pause_commit_s and self._provisional:
            self._committed.extend(self._provisional)
            self._provisional = []
        return self.view()

    def _merge(self, incoming: list[str]) -> list[str]:
        full = self._session()
        last = self._last_window
        if last and len(last) <= len(full) and _keys(full[-len(last) :]) == _keys(last):
            head = full[: -len(last)]
            return merge_window(head, merge_window(last, incoming))
        return merge_window(full, incoming)

    def _split(self, aligned: list[str]) -> None:
        keep = self.provisional_words
        if len(aligned) <= keep:
            if _has_prefix(aligned, self._committed) or not self._committed:
                self._committed = []
                self._provisional = aligned
            return
        cut = len(aligned) - keep
        self._committed = aligned[:cut]
        self._provisional = aligned[cut:]
