from src.adapters.fixture_adapter import FixtureAdapter
from src.core.aggregator import aggregate
from src.core.note_selector import select_typical_notes

DEDUP = "tests/fixtures/search_contents_dedup.jsonl"


def _notes():
    r = FixtureAdapter(DEDUP).search("留学辅导", 1, 50, "2026-06-24T00:00:00Z")
    return aggregate([r])[0]


def test_select_top1_per_account():
    sel = select_typical_notes(_notes(), top_per_account=1)
    by = {t.account_id: t for t in sel}
    assert by["U1"].note_id == "N1"  # 互动最高
    assert by["U2"].note_id == "N3"
    assert by["U1"].selection_reason == "top by interaction"


def test_top2_returns_both_for_u1():
    sel = [t for t in select_typical_notes(_notes(), top_per_account=2) if t.account_id == "U1"]
    assert {t.note_id for t in sel} == {"N1", "N2"}
