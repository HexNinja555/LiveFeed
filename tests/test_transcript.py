from livefeed.captions import clean_caption, is_ui_chrome
from livefeed.transcript import TranscriptBuffer, merge_window, words


def test_chrome_names_are_ignored() -> None:
    assert is_ui_chrome("Live Captions")
    assert is_ui_chrome("Ready to show live captions")
    assert clean_caption("Ready to show live captions\nhello there") == "hello there"


def test_merge_extends_overlapping_window() -> None:
    session = words("tell me about a production incident you owned")
    window = words("a production incident you owned last winter")
    merged = merge_window(session, window)
    assert " ".join(merged) == "tell me about a production incident you owned last winter"


def test_gap_appends_repeated_sentence() -> None:
    buffer = TranscriptBuffer(provisional_words=4, pause_commit_s=0.2)
    first = buffer.ingest("What is your strongest skill?", now=1.0)
    assert "strongest" in first.full
    paused = buffer.ingest("", now=2.0)
    assert paused.full
    again = buffer.ingest("What is your strongest skill?", now=2.1)
    assert again.full.lower().count("strongest") >= 2
