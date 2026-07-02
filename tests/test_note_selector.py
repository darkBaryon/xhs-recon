from src.adapters.fixture_adapter import FixtureAdapter
from src.core.aggregator import aggregate
from src.core.note_selector import select_typical_notes
from src.models import Note

DEDUP = "tests/fixtures/search_contents_dedup.jsonl"
NOW = "2026-07-02T00:00:00+00:00"


def _notes():
    r = FixtureAdapter(DEDUP).search("留学辅导", 1, 50, "2026-06-24T00:00:00Z")
    return aggregate([r])[0]


def _note(
    note_id: str,
    *,
    account_id: str = "U",
    like_count: int = 1,
    collect_count: int = 0,
    comment_count: int = 0,
    published_at: str = NOW,
) -> Note:
    return Note(
        note_id=note_id,
        account_id=account_id,
        title=f"title {note_id}",
        body="body",
        tags=[],
        url=f"https://example.com/{note_id}",
        like_count=like_count,
        collect_count=collect_count,
        comment_count=comment_count,
        published_at=published_at,
        collected_at=NOW,
        source_keywords=["留学辅导"],
        raw_path="fixture.jsonl",
    )


def test_select_top1_per_account():
    sel = select_typical_notes(_notes(), top_per_account=1)
    by = {t.account_id: t for t in sel}
    assert by["U1"].note_id == "N1"  # 互动最高
    assert by["U2"].note_id == "N3"
    assert by["U1"].selection_reason == "top by interaction"


def test_top2_returns_both_for_u1():
    sel = [t for t in select_typical_notes(_notes(), top_per_account=2) if t.account_id == "U1"]
    assert {t.note_id for t in sel} == {"N1", "N2"}


def test_half_life_zero_keeps_interaction_ranking():
    notes = [
        _note("new", like_count=100, published_at="2026-06-25T00:00:00+00:00"),
        _note("old", like_count=10000, published_at="2025-05-28T00:00:00+00:00"),
    ]

    sel = select_typical_notes(notes, top_per_account=1, half_life_days=0, now_iso=NOW)

    assert sel[0].note_id == "old"
    assert sel[0].note_score == 10000
    assert sel[0].selection_reason == "top by interaction"


def test_recency_decay_lets_recent_note_beat_old_hit():
    notes = [
        _note("new", like_count=100, published_at="2026-06-25T00:00:00+00:00"),
        _note("old", like_count=10000, published_at="2025-05-28T00:00:00+00:00"),
    ]

    sel = select_typical_notes(notes, top_per_account=1, half_life_days=14, now_iso=NOW)

    assert sel[0].note_id == "new"
    assert sel[0].selection_reason == "top by interaction×recency"


def test_recency_decay_penalizes_missing_published_at():
    notes = [
        _note("missing", like_count=10000, published_at=""),
        _note("fresh", like_count=100, published_at=NOW),
    ]

    sel = select_typical_notes(notes, top_per_account=1, half_life_days=14, now_iso=NOW)

    assert sel[0].note_id == "fresh"


def test_future_published_at_does_not_score_above_today():
    notes = [
        _note("today", like_count=100, published_at=NOW),
        _note("future", like_count=100, published_at="2026-07-12T00:00:00+00:00"),
    ]

    sel = select_typical_notes(notes, top_per_account=2, half_life_days=14, now_iso=NOW)
    by_id = {note.note_id: note for note in sel}

    assert by_id["future"].note_score == by_id["today"].note_score
