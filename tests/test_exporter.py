import csv
from pathlib import Path

from src.core.exporter import export_all
from src.models import Account, AccountRank, Comment, Note, TypicalNote, WatchAccount


def _data():
    acc = Account(
        account_id="U1",
        nickname="作者甲",
        source_keywords=["留学辅导", "essay辅导"],
        note_count=2,
        first_seen_at="2026",
        last_seen_at="2026",
    )
    note = Note(
        note_id="N1",
        account_id="U1",
        title="标题",
        body="正文",
        tags=["留学"],
        url="http://x/N1",
        like_count=10000,
        collect_count=100,
        comment_count=10,
        published_at="2024",
        collected_at="2026",
        source_keywords=["留学辅导"],
        raw_path="p",
    )
    rank = AccountRank(
        account_id="U1",
        nickname="作者甲",
        relevant_note_count=2,
        keyword_hit_count=2,
        avg_interaction=5000.0,
        account_score=83.3,
        note_ids=["N1", "N2"],
    )
    tn = TypicalNote(
        account_id="U1",
        note_id="N1",
        title="标题",
        url="http://x/N1",
        note_score=10230.0,
        selection_reason="top by interaction",
    )
    return [acc], [note], [rank], [tn]


def test_export_all_writes_five_files(tmp_path):
    accounts, notes, ranks, tns = _data()
    paths = export_all(tmp_path, accounts=accounts, notes=notes, ranks=ranks, typical_notes=tns)
    for key in ["accounts", "notes", "account_rank", "typical_notes", "report_input"]:
        assert Path(paths[key]).exists()
    assert "comments" not in paths
    assert "watchlist" not in paths
    assert "creator_notes" not in paths
    assert not (tmp_path / "watchlist.csv").exists()
    assert not (tmp_path / "creator_notes.csv").exists()

    with open(tmp_path / "accounts.csv", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == [
        "account_id",
        "nickname",
        "source_keywords",
        "note_count",
        "first_seen_at",
        "last_seen_at",
    ]
    assert rows[1][2] == "留学辅导|essay辅导"  # list 字段 | 连接

    md = (tmp_path / "report_input.md").read_text(encoding="utf-8")
    assert "作者甲" in md


def test_export_all_writes_comments_and_weaves_top_report_comments(tmp_path):
    accounts, notes, ranks, tns = _data()
    comments = [
        Comment(body="低赞评论", note_id="N1", like_count=3, collected_at="2026"),
        Comment(body="高赞评论", note_id="N1", like_count=20, collected_at="2026"),
        Comment(body="其他笔记评论", note_id="N2", like_count=99, collected_at="2026"),
    ]

    paths = export_all(
        tmp_path,
        accounts=accounts,
        notes=notes,
        ranks=ranks,
        typical_notes=tns,
        comments=comments,
        comment_top_k=1,
    )

    with open(paths["comments"], encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["body", "note_id", "like_count", "collected_at"]
    assert rows[1] == ["低赞评论", "N1", "3", "2026"]

    md = (tmp_path / "report_input.md").read_text(encoding="utf-8")
    assert "高赞评论" in md
    assert "低赞评论" not in md
    assert "其他笔记评论" not in md


def test_export_all_writes_watchlist_and_creator_notes_when_passed(tmp_path):
    accounts, notes, ranks, tns = _data()
    watchlist = [WatchAccount(account_id="U1", nickname="作者甲", source="manual")]

    paths = export_all(
        tmp_path,
        accounts=accounts,
        notes=notes,
        ranks=ranks,
        typical_notes=tns,
        watchlist=watchlist,
        creator_notes=notes,
    )

    with open(paths["watchlist"], encoding="utf-8") as f:
        watch_rows = list(csv.reader(f))
    assert watch_rows == [
        ["account_id", "nickname", "source"],
        ["U1", "作者甲", "manual"],
    ]

    with open(paths["creator_notes"], encoding="utf-8") as f:
        creator_rows = list(csv.reader(f))
    assert creator_rows[0] == [
        "note_id",
        "account_id",
        "title",
        "body",
        "tags",
        "url",
        "like_count",
        "collect_count",
        "comment_count",
        "published_at",
        "collected_at",
        "source_keywords",
        "raw_path",
    ]
    assert creator_rows[1][0] == "N1"
    assert creator_rows[1][11] == "留学辅导"
