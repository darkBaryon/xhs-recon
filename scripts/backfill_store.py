#!/usr/bin/env python3
"""把历史导出（data/exports/*/ 的 CSV）回填进 MySQL 库——迁移用，也供增量验证。

切库模型时不该从空库起步重爬。本脚本扫全部历史运行目录，把 notes/creator_notes/
accounts/comments 灌进库（幂等去重），并对已有评论的笔记标记 comments_fetched_at，
使切换后「已采过的不再采」立即生效。

用法:  python scripts/backfill_store.py [导出根=data/exports] [库名=xhs_recon]
"""

import csv
import sys
from pathlib import Path

# 允许脚本直接运行时 import src.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.adapters.mysql_store import MySQLStore  # noqa: E402
from src.models import Account, Comment, Note  # noqa: E402


def _split_pipe(s: str) -> list[str]:
    return s.split("|") if s else []


def _rows(path: Path) -> list[dict]:
    if not path.exists() or path.is_symlink():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _to_note(r: dict) -> Note:
    return Note(
        note_id=r["note_id"],
        account_id=r["account_id"],
        title=r["title"],
        body=r["body"],
        tags=_split_pipe(r["tags"]),
        url=r["url"],
        like_count=int(r["like_count"] or 0),
        collect_count=int(r["collect_count"] or 0),
        comment_count=int(r["comment_count"] or 0),
        published_at=r["published_at"],
        collected_at=r["collected_at"],
        source_keywords=_split_pipe(r["source_keywords"]),
        raw_path=r["raw_path"],
    )


def _to_account(r: dict) -> Account:
    return Account(
        account_id=r["account_id"],
        nickname=r["nickname"],
        source_keywords=_split_pipe(r["source_keywords"]),
        note_count=int(r["note_count"] or 0),
        first_seen_at=r["first_seen_at"],
        last_seen_at=r["last_seen_at"],
    )


def backfill(exports_root: Path, store: MySQLStore) -> dict[str, int]:
    # 时间序遍历：目录名是 compact run_id，字典序即时间序；后跑的覆盖（刷新易变字段）
    run_dirs = sorted(d for d in exports_root.iterdir() if d.is_dir() and not d.is_symlink())
    n_notes = n_accts = n_comments = 0
    commented_at: dict[str, str] = {}  # note_id -> 该笔记评论的最近 collected_at
    for d in run_dirs:
        for r in _rows(d / "accounts.csv"):
            store.upsert_accounts([_to_account(r)])
            n_accts += 1
        for fname in ("notes.csv", "creator_notes.csv"):
            batch = [_to_note(r) for r in _rows(d / fname)]
            if batch:
                store.upsert_notes(batch)
                n_notes += len(batch)
        crows = _rows(d / "comments.csv")
        if crows:
            store.upsert_comments(
                [
                    Comment(
                        body=r["body"],
                        note_id=r["note_id"],
                        like_count=int(r["like_count"] or 0),
                        collected_at=r["collected_at"],
                    )
                    for r in crows
                ]
            )
            n_comments += len(crows)
            for r in crows:
                at = r["collected_at"]
                if at > commented_at.get(r["note_id"], ""):
                    commented_at[r["note_id"]] = at
    # 有评论的笔记 → 标记「已抓过评论」，增量段据此跳过
    for nid, at in commented_at.items():
        store.mark_comments_fetched([nid], at)

    return {
        "run_dirs": len(run_dirs),
        "note_rows": n_notes,
        "unique_notes": len(store.known_note_ids()),
        "account_rows": n_accts,
        "comment_rows": n_comments,
        "notes_marked_commented": len(commented_at),
    }


def main() -> int:
    exports_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/exports")
    database = sys.argv[2] if len(sys.argv) > 2 else "xhs_recon"
    if not exports_root.exists():
        print(f"导出根不存在：{exports_root}", file=sys.stderr)
        return 1
    store = MySQLStore(database)
    stats = backfill(exports_root, store)
    store.close()
    print(f"回填完成 → MySQL/{database}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
