from src.adapters.fixture_adapter import FixtureAdapter
from src.core.account_ranker import profile_accounts, rank_accounts
from src.core.aggregator import aggregate
from src.models import Note, WatchAccount

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


def _note(
    note_id: str,
    account_id: str,
    *,
    title: str = "",
    body: str = "",
    tags: list[str] | None = None,
    published_at: str = "2026-07-01T00:00:00+00:00",
) -> Note:
    return Note(
        note_id=note_id,
        account_id=account_id,
        title=title,
        body=body,
        tags=tags or [],
        url=f"https://example.com/{note_id}",
        like_count=0,
        collect_count=0,
        comment_count=0,
        published_at=published_at,
        collected_at="2026-07-03T00:00:00+00:00",
        source_keywords=[],
        raw_path="fixture",
    )


def test_profile_accounts_scores_vertical_ratio_and_recent_count():
    watchlist = [
        WatchAccount(account_id="A1", nickname="账号一", source="manual"),
        WatchAccount(account_id="A2", nickname="账号二", source="manual"),
        WatchAccount(account_id="A3", nickname="空账号", source="manual"),
    ]
    notes = [
        _note("N1", "A1", title="留学辅导案例", published_at="2026-07-01T00:00:00+00:00"),
        _note("N2", "A1", body="Essay辅导复盘", published_at="2026-06-20T00:00:00+00:00"),
        _note("N3", "A1", tags=["生活"], published_at="2026-05-01T00:00:00+00:00"),
        _note("N4", "A2", tags=["FINAL自救"], published_at=""),
    ]

    profiles = profile_accounts(
        watchlist,
        notes,
        ["留学辅导", "essay辅导", "final自救"],
        30,
        "2026-07-03T00:00:00+00:00",
    )

    assert [p.account_id for p in profiles] == ["A1", "A2", "A3"]
    assert profiles[0].vertical_ratio == 2 / 3
    assert profiles[0].recent_note_count == 2
    assert profiles[0].profile_score == 10.0 * (2 / 3) + 2
    assert profiles[1].vertical_ratio == 1.0
    assert profiles[1].recent_note_count == 0
    assert profiles[1].profile_score == 10.0
    assert profiles[2].vertical_ratio == 0.0
    assert profiles[2].recent_note_count == 0
    assert profiles[2].profile_score == 0.0


def test_profile_accounts_window_zero_keeps_all_and_weights_are_configurable():
    watchlist = [WatchAccount(account_id="A1", nickname="账号一", source="manual")]
    notes = [
        _note("N1", "A1", title="留学辅导案例", published_at=""),
        _note("N2", "A1", title="其他内容", published_at="2026-05-01T00:00:00+00:00"),
    ]

    profiles = profile_accounts(
        watchlist,
        notes,
        ["留学辅导"],
        0,
        "2026",
        {"vertical": 20.0, "activity": 2.0},
    )

    assert profiles[0].vertical_ratio == 0.5
    assert profiles[0].recent_note_count == 2
    assert profiles[0].profile_score == 20.0 * 0.5 + 2.0 * 2
