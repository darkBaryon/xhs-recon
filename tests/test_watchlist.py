from src.core.watchlist import build_watchlist
from src.models import AccountRank


def _rank(account_id: str, nickname: str, score: float) -> AccountRank:
    return AccountRank(
        account_id=account_id,
        nickname=nickname,
        relevant_note_count=1,
        keyword_hit_count=1,
        avg_interaction=0.0,
        account_score=score,
        note_ids=[f"note-{account_id}"],
    )


def test_build_watchlist_keeps_manual_first_then_auto_rank_order():
    ranked = [
        _rank("000000000000000000000001", "Auto One", 30),
        _rank("000000000000000000000002", "Auto Two", 20),
    ]

    watchlist = build_watchlist(
        ranked,
        manual_ids=["000000000000000000000099"],
        auto_top_n=2,
        max_total=5,
    )

    assert [w.account_id for w in watchlist] == [
        "000000000000000000000099",
        "000000000000000000000001",
        "000000000000000000000002",
    ]
    assert [w.source for w in watchlist] == ["manual", "auto", "auto"]


def test_build_watchlist_preserves_manual_when_manual_overlaps_auto_window():
    ranked = [
        _rank("000000000000000000000001", "Rank One", 30),
        _rank("000000000000000000000002", "Rank Two", 20),
        _rank("000000000000000000000003", "Rank Three", 10),
    ]

    watchlist = build_watchlist(
        ranked,
        manual_ids=["000000000000000000000001"],
        auto_top_n=2,
        max_total=5,
    )

    assert [w.account_id for w in watchlist] == [
        "000000000000000000000001",
        "000000000000000000000002",
    ]
    assert watchlist[0].source == "manual"
    assert watchlist[0].nickname == "Rank One"


def test_build_watchlist_truncates_to_max_total():
    ranked = [
        _rank("000000000000000000000001", "Auto One", 30),
        _rank("000000000000000000000002", "Auto Two", 20),
    ]

    watchlist = build_watchlist(
        ranked,
        manual_ids=["000000000000000000000099"],
        auto_top_n=2,
        max_total=2,
    )

    assert [w.account_id for w in watchlist] == [
        "000000000000000000000099",
        "000000000000000000000001",
    ]


def test_build_watchlist_does_not_fill_beyond_auto_window():
    ranked = [
        _rank("000000000000000000000001", "Rank One", 30),
        _rank("000000000000000000000002", "Rank Two", 20),
        _rank("000000000000000000000003", "Rank Three", 10),
    ]

    watchlist = build_watchlist(
        ranked,
        manual_ids=["000000000000000000000001", "000000000000000000000002"],
        auto_top_n=2,
        max_total=5,
    )

    assert [w.account_id for w in watchlist] == [
        "000000000000000000000001",
        "000000000000000000000002",
    ]


def test_build_watchlist_empty_ranked_keeps_manual_with_blank_nickname():
    watchlist = build_watchlist(
        ranked=[],
        manual_ids=["000000000000000000000099"],
        auto_top_n=2,
        max_total=5,
    )

    assert watchlist[0].account_id == "000000000000000000000099"
    assert watchlist[0].nickname == ""
    assert watchlist[0].source == "manual"
