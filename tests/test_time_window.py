import pytest

from src.core.time_window import filter_notes
from src.models import Note

NOW = "2026-07-02T00:00:00+00:00"


def _note(note_id: str, published_at: str) -> Note:
    return Note(
        note_id=note_id,
        account_id="account",
        title=f"title {note_id}",
        body="body",
        tags=[],
        url=f"https://example.com/{note_id}",
        like_count=1,
        collect_count=0,
        comment_count=0,
        published_at=published_at,
        collected_at=NOW,
        source_keywords=["留学辅导"],
        raw_path="fixture.jsonl",
    )


def test_filter_notes_keeps_notes_inside_window():
    notes = [_note("inside", "2026-06-20T00:00:00+00:00")]

    filtered, stats = filter_notes(notes, window_days=30, now_iso=NOW)

    assert [n.note_id for n in filtered] == ["inside"]
    assert stats.kept == 1
    assert stats.out_of_window == 0
    assert stats.missing_time == 0


def test_filter_notes_drops_notes_outside_window():
    notes = [_note("old", "2026-05-01T00:00:00+00:00")]

    filtered, stats = filter_notes(notes, window_days=30, now_iso=NOW)

    assert filtered == []
    assert stats.kept == 0
    assert stats.out_of_window == 1
    assert stats.missing_time == 0


def test_filter_notes_keeps_exact_window_boundary():
    notes = [_note("boundary", "2026-06-02T00:00:00+00:00")]

    filtered, stats = filter_notes(notes, window_days=30, now_iso=NOW)

    assert [n.note_id for n in filtered] == ["boundary"]
    assert stats.kept == 1


def test_filter_notes_counts_missing_time_as_outside_window():
    notes = [_note("missing", "")]

    filtered, stats = filter_notes(notes, window_days=30, now_iso=NOW)

    assert filtered == []
    assert stats.kept == 0
    assert stats.out_of_window == 0
    assert stats.missing_time == 1


def test_filter_notes_window_zero_passes_through():
    notes = [_note("missing", ""), _note("old", "2020-01-01T00:00:00+00:00")]

    filtered, stats = filter_notes(notes, window_days=0, now_iso=NOW)

    assert filtered is notes
    assert stats.kept == 2
    assert stats.out_of_window == 0
    assert stats.missing_time == 0


def test_filter_notes_rejects_invalid_now_iso():
    with pytest.raises(ValueError, match="now_iso"):
        filter_notes([_note("inside", "2026-06-20T00:00:00+00:00")], 30, "bad")
