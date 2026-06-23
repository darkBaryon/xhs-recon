from src.adapters.fixture_adapter import FixtureAdapter
from src.core.aggregator import aggregate

DEDUP = "tests/fixtures/search_contents_dedup.jsonl"


def _run():
    r = FixtureAdapter(DEDUP).search("留学辅导", 1, 50, "2026-06-24T00:00:00Z")
    return aggregate([r])


def test_notes_deduped_by_note_id():
    notes, _ = _run()
    assert sorted(n.note_id for n in notes) == ["N1", "N2", "N3"]


def test_same_note_cross_keyword_merges_source_keywords_in_order():
    notes, _ = _run()
    n1 = next(n for n in notes if n.note_id == "N1")
    assert n1.source_keywords == ["留学辅导", "essay辅导"]


def test_accounts_deduped_with_note_count():
    _, accounts = _run()
    by = {a.account_id: a for a in accounts}
    assert set(by) == {"U1", "U2"}
    assert by["U1"].note_count == 2  # N1 + N2，重复的 N1 不再计
    assert by["U2"].note_count == 1
    assert set(by["U1"].source_keywords) == {"留学辅导", "essay辅导"}
    assert by["U1"].nickname == "作者甲"
