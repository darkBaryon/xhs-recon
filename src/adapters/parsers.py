"""xhs search_contents JSONL → 领域模型（含边界归一化）。

平台专属解析隔离在 adapter 层；core 永不触碰原始 JSONL 的字段形状。
"""

import json
from datetime import datetime, timezone

from src.models import Account, Note


def normalize_count(raw) -> int:
    """本地化互动计数 → int：'1万'→10000，'1.2万'→12000，'10万+'→100000，'921'→921，空/异常→0。"""
    if raw is None:
        return 0
    s = str(raw).strip().replace("+", "")
    if not s:
        return 0
    try:
        if s.endswith("万"):
            return int(float(s[:-1]) * 10000)
        if s.endswith("千"):
            return int(float(s[:-1]) * 1000)
        return int(float(s))
    except ValueError:
        return 0


def split_tags(raw) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in str(raw).split(",") if t.strip()]


def epoch_ms_to_iso(ms) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return ""


def _row_keyword(row: dict, fallback: str) -> str:
    return row.get("source_keyword") or fallback


def parse_note(row: dict, *, keyword: str, collected_at: str, raw_path: str) -> Note:
    kw = _row_keyword(row, keyword)
    return Note(
        note_id=row.get("note_id", ""),
        account_id=row.get("user_id", ""),
        title=row.get("title", ""),
        body=row.get("desc", ""),
        tags=split_tags(row.get("tag_list")),
        url=row.get("note_url", ""),
        like_count=normalize_count(row.get("liked_count")),
        collect_count=normalize_count(row.get("collected_count")),
        comment_count=normalize_count(row.get("comment_count")),
        published_at=epoch_ms_to_iso(row.get("time")),
        collected_at=collected_at,
        source_keywords=[kw] if kw else [],
        raw_path=raw_path,
    )


def parse_account(row: dict, *, keyword: str, collected_at: str) -> Account:
    kw = _row_keyword(row, keyword)
    return Account(
        account_id=row.get("user_id", ""),
        nickname=row.get("nickname", ""),
        source_keywords=[kw] if kw else [],
        note_count=1,
        first_seen_at=collected_at,
        last_seen_at=collected_at,
    )


def parse_jsonl_lines(
    lines, *, keyword: str, collected_at: str, raw_path: str
) -> tuple[list[Note], list[Account]]:
    notes: list[Note] = []
    accounts: list[Account] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        notes.append(parse_note(row, keyword=keyword, collected_at=collected_at, raw_path=raw_path))
        accounts.append(parse_account(row, keyword=keyword, collected_at=collected_at))
    return notes, accounts
