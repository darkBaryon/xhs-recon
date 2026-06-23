"""导出 5 个结构化文件供 LLM 分析。CSV 用 stdlib；list 字段以 | 连接。

文件名与列稳定（导出契约）：accounts/notes/account_rank/typical_notes/report_input。
"""

import csv
from pathlib import Path

from src.models import Account, AccountRank, Note, TypicalNote

PIPE = "|"


def _join(xs: list[str]) -> str:
    return PIPE.join(xs)


def _write_csv(path: Path, header: list[str], rows: list[list]) -> str:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return str(path)


def _write_report(path: Path, ranks: list[AccountRank], typical: list[TypicalNote]) -> str:
    tn_by_acc: dict[str, list[TypicalNote]] = {}
    for t in typical:
        tn_by_acc.setdefault(t.account_id, []).append(t)
    lines = ["# 竞品账号研究输入", ""]
    for r in ranks:
        lines.append(f"## {r.nickname}（{r.account_id}）")
        lines.append(
            f"- 相关笔记 {r.relevant_note_count} · 关键词命中 {r.keyword_hit_count}"
            f" · 均互动 {r.avg_interaction:.0f} · 评分 {r.account_score:.2f}"
        )
        for t in tn_by_acc.get(r.account_id, []):
            lines.append(f"  - [{t.title}]({t.url}) · note_score {t.note_score:.0f}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def export_all(
    out_dir,
    *,
    accounts: list[Account],
    notes: list[Note],
    ranks: list[AccountRank],
    typical_notes: list[TypicalNote],
) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    paths["accounts"] = _write_csv(
        out / "accounts.csv",
        [
            "account_id",
            "nickname",
            "source_keywords",
            "note_count",
            "first_seen_at",
            "last_seen_at",
        ],
        [
            [
                a.account_id,
                a.nickname,
                _join(a.source_keywords),
                a.note_count,
                a.first_seen_at,
                a.last_seen_at,
            ]
            for a in accounts
        ],
    )
    paths["notes"] = _write_csv(
        out / "notes.csv",
        [
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
        ],
        [
            [
                n.note_id,
                n.account_id,
                n.title,
                n.body,
                _join(n.tags),
                n.url,
                n.like_count,
                n.collect_count,
                n.comment_count,
                n.published_at,
                n.collected_at,
                _join(n.source_keywords),
                n.raw_path,
            ]
            for n in notes
        ],
    )
    paths["account_rank"] = _write_csv(
        out / "account_rank.csv",
        [
            "account_id",
            "nickname",
            "relevant_note_count",
            "keyword_hit_count",
            "avg_interaction",
            "account_score",
            "note_ids",
        ],
        [
            [
                r.account_id,
                r.nickname,
                r.relevant_note_count,
                r.keyword_hit_count,
                r.avg_interaction,
                r.account_score,
                _join(r.note_ids),
            ]
            for r in ranks
        ],
    )
    paths["typical_notes"] = _write_csv(
        out / "typical_notes.csv",
        ["account_id", "note_id", "title", "url", "note_score", "selection_reason"],
        [
            [t.account_id, t.note_id, t.title, t.url, t.note_score, t.selection_reason]
            for t in typical_notes
        ],
    )
    paths["report_input"] = _write_report(out / "report_input.md", ranks, typical_notes)
    return paths
