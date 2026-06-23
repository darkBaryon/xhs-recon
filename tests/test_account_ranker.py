from src.adapters.fixture_adapter import FixtureAdapter
from src.core.account_ranker import rank_accounts
from src.core.aggregator import aggregate

DEDUP = "tests/fixtures/search_contents_dedup.jsonl"


def _agg():
    r = FixtureAdapter(DEDUP).search("留学辅导", 1, 50, "2026-06-24T00:00:00Z")
    return aggregate([r])


def test_rank_orders_by_score_and_fills_fields():
    notes, accounts = _agg()
    ranks = rank_accounts(accounts, notes)
    assert ranks[0].account_id == "U1"  # 2 笔记 + 高互动 → 居首
    assert ranks[0].relevant_note_count == 2
    assert ranks[0].keyword_hit_count == 2
    assert set(ranks[0].note_ids) == {"N1", "N2"}
    assert ranks[0].account_score > ranks[1].account_score


def test_weights_are_configurable():
    notes, accounts = _agg()
    # 把互动权重抬高，分数应随之变化（验证 config 入口真生效）
    base = rank_accounts(accounts, notes)[0].account_score
    boosted = rank_accounts(accounts, notes, {"interaction": 1.0})[0].account_score
    assert boosted > base
