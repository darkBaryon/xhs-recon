"""xhs search_contents JSONL → 领域模型（含边界归一化）。

平台专属解析隔离在 adapter 层；core 永不触碰原始 JSONL 的字段形状。
"""

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from src.models import Account, Comment, CreatorProfile, Note

CREATOR_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")


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
        return int(float(s))
    except ValueError:
        return 0


def split_tags(raw) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in str(raw).split(",") if t.strip()]


def normalize_creator_ref(ref: str) -> str:
    original = ref
    text = str(ref).strip()
    if CREATOR_ID_RE.fullmatch(text):
        return text.lower()

    parsed = urlparse(text)
    path_parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme == "https"
        and parsed.netloc.lower() == "www.xiaohongshu.com"
        and len(path_parts) == 3
        and path_parts[0] == "user"
        and path_parts[1] == "profile"
        and CREATOR_ID_RE.fullmatch(path_parts[2])
    ):
        return path_parts[2].lower()

    raise ValueError(f"invalid creator ref: {original}")


def epoch_ms_to_iso(ms) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return ""


def card_time_to_iso(raw_ms, text: str, collected_at: str) -> str:
    """Turn the date label visible on a search card into an ISO timestamp."""
    exact = epoch_ms_to_iso(raw_ms) if raw_ms not in (None, "", 0, "0") else ""
    if exact:
        return exact
    label = str(text or "").strip()
    try:
        collected = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if label == "昨天":
        return (collected - timedelta(days=1)).isoformat()
    if label == "前天":
        return (collected - timedelta(days=2)).isoformat()
    days_ago = re.fullmatch(r"(\d+)天前", label)
    if days_ago:
        return (collected - timedelta(days=int(days_ago.group(1)))).isoformat()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(label, fmt)
            return parsed.replace(tzinfo=collected.tzinfo).isoformat()
        except ValueError:
            pass
    for fmt in ("%m-%d", "%m/%d"):
        try:
            parsed = datetime.strptime(label, fmt).replace(
                year=collected.year, tzinfo=collected.tzinfo
            )
        except ValueError:
            continue
        if parsed > collected:
            parsed = parsed.replace(year=collected.year - 1)
        return parsed.isoformat()
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
        published_at=card_time_to_iso(
            row.get("time"), row.get("publish_time_text", ""), collected_at
        ),
        collected_at=collected_at,
        source_keywords=[kw] if kw else [],
        raw_path=raw_path,
        # 全量字段（MediaCrawler 已在 jsonl 里给了，之前被裁掉）
        note_type=row.get("type") or "",
        video_url=row.get("video_url") or "",
        share_count=normalize_count(row.get("share_count")),
        author_avatar=row.get("avatar") or "",
        ip_location=row.get("ip_location") or "",
        image_urls=split_tags(row.get("image_list")),  # 逗号拼接的图片 URL
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


def parse_comment(row: dict, *, collected_at: str) -> Comment:
    # 全量：保留评论者身份/楼层/配图（推翻早期四项裁剪红线，用户明确扩范围）。
    # 二级评论在 MediaCrawler 输出里也是一条 comment，靠 parent_comment_id 区分。
    return Comment(
        body=row.get("content", ""),
        note_id=row.get("note_id", ""),
        like_count=normalize_count(row.get("like_count")),
        collected_at=collected_at,
        comment_id=str(row.get("comment_id") or ""),
        parent_comment_id=str(row.get("parent_comment_id") or ""),
        author_id=row.get("user_id") or "",
        author_nickname=row.get("nickname") or "",
        author_avatar=row.get("avatar") or "",
        ip_location=row.get("ip_location") or "",
        pictures=split_tags(row.get("pictures")),
        sub_comment_count=normalize_count(row.get("sub_comment_count")),
        created_at=epoch_ms_to_iso(row.get("create_time")),
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


def _parse_tag_list(raw) -> dict[str, str]:
    """save_creator 的 tag_list 是 {tagType: name} 的 JSON 串；坏值降级空 dict。"""
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def _verify_type(raw) -> int:
    # 官方认证类型：缺字段（旧版 fork）或非法值 → -1（未知，区别于 0=未认证）
    if raw is None:
        return -1
    try:
        return int(raw)
    except (ValueError, TypeError):
        return -1


def parse_creator_profile(row: dict, *, collected_at: str) -> CreatorProfile:
    return CreatorProfile(
        account_id=row.get("user_id", ""),
        nickname=row.get("nickname", ""),
        red_id=str(row.get("red_id") or ""),
        verify_type=_verify_type(row.get("verify_type")),
        desc=row.get("desc") or "",
        fans=normalize_count(row.get("fans")),
        follows=normalize_count(row.get("follows")),
        interaction=normalize_count(row.get("interaction")),
        tags=_parse_tag_list(row.get("tag_list")),
        ip_location=row.get("ip_location") or "",
        collected_at=collected_at,
    )


def parse_creator_profiles_jsonl_lines(lines, *, collected_at: str) -> list[CreatorProfile]:
    profiles: list[CreatorProfile] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue  # 档案是软信号：坏行跳过，不坏整跑
        profiles.append(parse_creator_profile(row, collected_at=collected_at))
    return profiles


def parse_comments_jsonl_lines(lines, *, collected_at: str) -> list[Comment]:
    comments: list[Comment] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        comments.append(parse_comment(row, collected_at=collected_at))
    return comments
