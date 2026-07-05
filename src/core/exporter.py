"""导出 5 个结构化文件供 LLM 分析。CSV 用 stdlib；list 字段以 | 连接。

文件名与列稳定（导出契约）：accounts/notes/account_rank/typical_notes/report_input。
每张 CSV 表的列以「列名 → 取值」的 *_COLUMNS 声明一次，header 与行同源；
notes 与 creator_notes 列相同，共用 NOTE_COLUMNS。
"""

import csv
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.core.time_window import WindowFilterStats
from src.models import (
    Account,
    AccountRank,
    Comment,
    CreatorProfile,
    Note,
    TypicalNote,
    WatchAccount,
)

PIPE = "|"

# 一列 = (列名, 取值函数)。取值函数吃一个模型实例、出该列的单元格值（csv.writer 负责 str 化）。
Column = tuple[str, Callable[[Any], object]]


def _join(xs: list[str]) -> str:
    return PIPE.join(xs)


def _write_csv(path: Path, header: list[str], rows: list[list]) -> str:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return str(path)


def _write_model_csv(path: Path, columns: list[Column], rows: list) -> str:
    """按列定义写一张 CSV：header 取列名，每行按取值函数求值。列顺序即导出契约。"""
    return _write_csv(
        path,
        [name for name, _ in columns],
        [[accessor(row) for _, accessor in columns] for row in rows],
    )


ACCOUNT_COLUMNS: list[Column] = [
    ("account_id", lambda a: a.account_id),
    ("nickname", lambda a: a.nickname),
    ("source_keywords", lambda a: _join(a.source_keywords)),
    ("note_count", lambda a: a.note_count),
    ("first_seen_at", lambda a: a.first_seen_at),
    ("last_seen_at", lambda a: a.last_seen_at),
]

# notes.csv 与 creator_notes.csv 列完全一致，共用这份定义
NOTE_COLUMNS: list[Column] = [
    ("note_id", lambda n: n.note_id),
    ("account_id", lambda n: n.account_id),
    ("title", lambda n: n.title),
    ("body", lambda n: n.body),
    ("tags", lambda n: _join(n.tags)),
    ("url", lambda n: n.url),
    ("like_count", lambda n: n.like_count),
    ("collect_count", lambda n: n.collect_count),
    ("comment_count", lambda n: n.comment_count),
    ("published_at", lambda n: n.published_at),
    ("collected_at", lambda n: n.collected_at),
    ("source_keywords", lambda n: _join(n.source_keywords)),
    ("raw_path", lambda n: n.raw_path),
]

ACCOUNT_RANK_COLUMNS: list[Column] = [
    ("account_id", lambda r: r.account_id),
    ("nickname", lambda r: r.nickname),
    ("relevant_note_count", lambda r: r.relevant_note_count),
    ("keyword_hit_count", lambda r: r.keyword_hit_count),
    ("avg_interaction", lambda r: r.avg_interaction),
    ("account_score", lambda r: r.account_score),
    ("note_ids", lambda r: _join(r.note_ids)),
]

TYPICAL_NOTE_COLUMNS: list[Column] = [
    ("account_id", lambda t: t.account_id),
    ("note_id", lambda t: t.note_id),
    ("title", lambda t: t.title),
    ("url", lambda t: t.url),
    ("note_score", lambda t: t.note_score),
    ("selection_reason", lambda t: t.selection_reason),
]

WATCHLIST_COLUMNS: list[Column] = [
    ("account_id", lambda w: w.account_id),
    ("nickname", lambda w: w.nickname),
    ("source", lambda w: w.source),
]

# 专业度分项：vertical_ratio/profile_score 定点格式化是导出契约的一部分
ACCOUNT_PROFILE_COLUMNS: list[Column] = [
    ("account_id", lambda r: r.account_id),
    ("nickname", lambda r: r.nickname),
    ("vertical_ratio", lambda r: f"{r.vertical_ratio:.4f}"),
    ("recent_note_count", lambda r: r.recent_note_count),
    ("profile_score", lambda r: f"{r.profile_score:.2f}"),
]

CREATOR_PROFILE_COLUMNS: list[Column] = [
    ("account_id", lambda p: p.account_id),
    ("nickname", lambda p: p.nickname),
    ("verify_type", lambda p: p.verify_type),
    ("red_id", lambda p: p.red_id),
    ("fans", lambda p: p.fans),
    ("follows", lambda p: p.follows),
    ("interaction", lambda p: p.interaction),
    ("tags", lambda p: _join([f"{k}:{v}" for k, v in p.tags.items()])),
    ("desc", lambda p: p.desc),
    ("ip_location", lambda p: p.ip_location),
]

COMMENT_COLUMNS: list[Column] = [
    ("body", lambda c: c.body),
    ("note_id", lambda c: c.note_id),
    ("like_count", lambda c: c.like_count),
    ("collected_at", lambda c: c.collected_at),
]


def _clean_report_text(s: str) -> str:
    return " ".join(s.split())


def _write_report(
    path: Path,
    ranks: list[AccountRank],
    typical: list[TypicalNote],
    comments: list[Comment],
    comment_top_k: int,
) -> str:
    tn_by_acc: dict[str, list[TypicalNote]] = {}
    for t in typical:
        tn_by_acc.setdefault(t.account_id, []).append(t)
    comments_by_note: dict[str, list[Comment]] = {}
    for c in comments:
        comments_by_note.setdefault(c.note_id, []).append(c)
    for xs in comments_by_note.values():
        xs.sort(key=lambda c: c.like_count, reverse=True)

    lines = ["# 竞品账号研究输入", ""]
    for r in ranks:
        lines.append(f"## {r.nickname}（{r.account_id}）")
        lines.append(
            f"- 相关笔记 {r.relevant_note_count} · 关键词命中 {r.keyword_hit_count}"
            f" · 均互动 {r.avg_interaction:.0f} · 评分 {r.account_score:.2f}"
        )
        for t in tn_by_acc.get(r.account_id, []):
            lines.append(f"  - [{t.title}]({t.url}) · note_score {t.note_score:.0f}")
            for c in comments_by_note.get(t.note_id, [])[:comment_top_k]:
                lines.append(f"    - 评论 {c.like_count}赞：{_clean_report_text(c.body)}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def _watch_meta(watchlist: list[WatchAccount] | None) -> dict[str, WatchAccount]:
    return {account.account_id: account for account in watchlist or []}


def _ordered_topic_notes(notes: list[Note], watchlist: list[WatchAccount] | None) -> list[Note]:
    order = {account.account_id: i for i, account in enumerate(watchlist or [])}
    notes_by_acc: dict[str, list[Note]] = {}
    for note in notes:
        notes_by_acc.setdefault(note.account_id, []).append(note)

    account_ids = sorted(
        notes_by_acc, key=lambda account_id: (order.get(account_id, len(order)), account_id)
    )
    ordered: list[Note] = []
    for account_id in account_ids:
        ordered.extend(
            sorted(
                notes_by_acc[account_id],
                key=lambda note: (note.published_at, note.note_id),
                reverse=True,
            )
        )
    return ordered


def _write_topic_feed_jsonl(
    path: Path, notes: list[Note], watchlist: list[WatchAccount] | None
) -> str:
    watch_by_id = _watch_meta(watchlist)
    lines = []
    for note in _ordered_topic_notes(notes, watchlist):
        account = watch_by_id.get(note.account_id)
        lines.append(
            json.dumps(
                {
                    "account_id": note.account_id,
                    "nickname": account.nickname if account else "",
                    "source": account.source if account else "",
                    "note_id": note.note_id,
                    "title": note.title,
                    "body": note.body,
                    "tags": note.tags,
                    "url": note.url,
                    "published_at": note.published_at,
                    "collected_at": note.collected_at,
                    "like_count": note.like_count,
                    "collect_count": note.collect_count,
                    "comment_count": note.comment_count,
                },
                ensure_ascii=False,
            )
        )
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return str(path)


def _write_topic_feed_md(
    path: Path,
    notes: list[Note],
    stats: WindowFilterStats,
    window_days: int,
    watchlist: list[WatchAccount] | None,
) -> str:
    watch_by_id = _watch_meta(watchlist)
    ordered_notes = _ordered_topic_notes(notes, watchlist)
    account_count = len({note.account_id for note in ordered_notes})
    lines = [
        (
            f"窗口 {window_days} 天 · 入 feed {stats.kept} 条 · 出窗 {stats.out_of_window} "
            f"· 缺时间 {stats.missing_time} · 账号 {account_count}"
        ),
        "",
    ]
    current_account_id = None
    for note in ordered_notes:
        if note.account_id != current_account_id:
            account = watch_by_id.get(note.account_id)
            nickname = account.nickname if account else ""
            lines.extend([f"## {nickname}（{note.account_id}）", ""])
            current_account_id = note.account_id
        lines.append(f"- {note.published_at} {note.title} {note.url}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def export_watch_side(
    out_dir,
    *,
    watchlist: list[WatchAccount] | None = None,
    creator_notes: list[Note] | None = None,
    account_profiles: list[AccountRank] | None = None,
    topic_feed: list[Note] | None = None,
    topic_feed_stats: WindowFilterStats | None = None,
    topic_feed_window_days: int = 0,
    creator_profiles: list[CreatorProfile] | None = None,
) -> dict[str, str]:
    """watchlist 侧子集出口（None = 不写）；export_all 委托，sync 命令单独调用。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    if watchlist is not None:
        paths["watchlist"] = _write_model_csv(out / "watchlist.csv", WATCHLIST_COLUMNS, watchlist)
    if creator_notes is not None:
        paths["creator_notes"] = _write_model_csv(
            out / "creator_notes.csv", NOTE_COLUMNS, creator_notes
        )
    if account_profiles is not None:
        paths["account_profile"] = _write_model_csv(
            out / "account_profile.csv", ACCOUNT_PROFILE_COLUMNS, account_profiles
        )
    if topic_feed is not None:
        stats = topic_feed_stats or WindowFilterStats(
            kept=len(topic_feed), out_of_window=0, missing_time=0
        )
        paths["topic_feed_jsonl"] = _write_topic_feed_jsonl(
            out / "topic_feed.jsonl", topic_feed, watchlist
        )
        paths["topic_feed"] = _write_topic_feed_md(
            out / "topic_feed.md", topic_feed, stats, topic_feed_window_days, watchlist
        )
    if creator_profiles is not None:
        paths["creator_profiles"] = _write_model_csv(
            out / "creator_profiles.csv", CREATOR_PROFILE_COLUMNS, creator_profiles
        )
    return paths


def export_comments(
    out_dir,
    *,
    ranks: list[AccountRank],
    typical_notes: list[TypicalNote],
    comments: list[Comment],
    comment_top_k: int = 3,
) -> dict[str, str]:
    """comments.csv（评论非空时）+ report_input.md（无条件重写）的子集出口。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    if comments:
        paths["comments"] = _write_model_csv(out / "comments.csv", COMMENT_COLUMNS, comments)
    paths["report_input"] = _write_report(
        out / "report_input.md", ranks, typical_notes, comments, comment_top_k
    )
    return paths


def export_all(
    out_dir,
    *,
    accounts: list[Account],
    notes: list[Note],
    ranks: list[AccountRank],
    typical_notes: list[TypicalNote],
    comments: list[Comment] | None = None,
    comment_top_k: int = 3,
    watchlist: list[WatchAccount] | None = None,
    creator_notes: list[Note] | None = None,
    account_profiles: list[AccountRank] | None = None,
    topic_feed: list[Note] | None = None,
    topic_feed_stats: WindowFilterStats | None = None,
    topic_feed_window_days: int = 0,
    creator_profiles: list[CreatorProfile] | None = None,
) -> dict[str, str]:
    comments = comments or []
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    paths["accounts"] = _write_model_csv(out / "accounts.csv", ACCOUNT_COLUMNS, accounts)
    paths["notes"] = _write_model_csv(out / "notes.csv", NOTE_COLUMNS, notes)
    paths["account_rank"] = _write_model_csv(
        out / "account_rank.csv", ACCOUNT_RANK_COLUMNS, ranks
    )
    paths["typical_notes"] = _write_model_csv(
        out / "typical_notes.csv", TYPICAL_NOTE_COLUMNS, typical_notes
    )
    paths.update(
        export_watch_side(
            out,
            watchlist=watchlist,
            creator_notes=creator_notes,
            account_profiles=account_profiles,
            topic_feed=topic_feed,
            topic_feed_stats=topic_feed_stats,
            topic_feed_window_days=topic_feed_window_days,
            creator_profiles=creator_profiles,
        )
    )
    paths.update(
        export_comments(
            out,
            ranks=ranks,
            typical_notes=typical_notes,
            comments=comments,
            comment_top_k=comment_top_k,
        )
    )
    return paths
