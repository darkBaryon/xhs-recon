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


def test_build_watchlist_uses_manual_nickname_before_ranked_nickname():
    ranked = [_rank("000000000000000000000001", "Rank One", 30)]

    watchlist = build_watchlist(
        ranked,
        manual_ids=["000000000000000000000001"],
        auto_top_n=1,
        max_total=5,
        manual_nicknames={"000000000000000000000001": "Manual One"},
    )

    assert watchlist[0].nickname == "Manual One"


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


def test_build_watchlist_marks_self_source_and_orders_first():
    # self_ids 里的 manual → source="self" 且排最前
    watchlist = build_watchlist(
        [],
        manual_ids=["000000000000000000000010", "000000000000000000000099"],
        auto_top_n=0,
        max_total=5,
        self_ids={"000000000000000000000099"},
    )
    assert [(w.account_id, w.source) for w in watchlist] == [
        ("000000000000000000000099", "self"),  # 本方账号提前
        ("000000000000000000000010", "manual"),
    ]


def test_build_watchlist_self_survives_truncation():
    # 即便排在 manual 列表末尾，本方账号也不被 max_total 截掉
    ranked = [_rank("000000000000000000000001", "Auto", 30)]
    watchlist = build_watchlist(
        ranked,
        manual_ids=["000000000000000000000010", "000000000000000000000099"],
        auto_top_n=1,
        max_total=1,
        self_ids={"000000000000000000000099"},
    )
    assert [w.account_id for w in watchlist] == ["000000000000000000000099"]
    assert watchlist[0].source == "self"


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


def test_build_watchlist_truncation_warns_with_dropped_ids(caplog):
    """B6：超 max_total 砍尾必须留痕（manual 手写项被无声丢弃是事故）。"""
    import logging

    manual = ["a" * 24, "b" * 24, "c" * 24]
    with caplog.at_level(logging.WARNING, logger="src.core.watchlist"):
        result = build_watchlist([], manual, auto_top_n=0, max_total=2)
    assert len(result) == 2
    assert "截掉 1 个" in caplog.text
    assert "c" * 24 in caplog.text  # 被丢的是谁要说清


def test_build_watchlist_no_warning_when_within_cap(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="src.core.watchlist"):
        build_watchlist([], ["a" * 24], auto_top_n=0, max_total=5)
    assert "截掉" not in caplog.text
