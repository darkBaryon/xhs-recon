import hashlib
import json
from dataclasses import dataclass


def _loads(value, default):
    if not value:
        return default
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class LegacyImportReport:
    creators: int
    contents: int
    comments: int
    keywords: int
    media_assets: int
    dry_run: bool
    placeholder_creators: int = 0


class LegacyImporter:
    """同库旧表 → 候选新表的幂等单向导入；不删除、不回写旧表。"""

    def __init__(self, connection) -> None:
        self.connection = connection

    def read_legacy(self) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
        tables = ("accounts", "notes", "comments", "creator_profiles")
        rows = []
        with self.connection.cursor() as cursor:
            for table in tables:
                cursor.execute(f"SELECT * FROM {table}")
                rows.append(list(cursor.fetchall()))
        return tuple(rows)

    def run(self, *, dry_run: bool = False) -> LegacyImportReport:
        return self.import_rows(*self.read_legacy(), dry_run=dry_run)

    def import_rows(
        self,
        accounts: list[dict],
        notes: list[dict],
        comments: list[dict],
        profiles: list[dict],
        *,
        dry_run: bool = False,
    ) -> LegacyImportReport:
        profile_by_id = {row["account_id"]: row for row in profiles}
        account_by_id = {row["account_id"]: row for row in accounts}
        note_times_by_account: dict[str, list[str]] = {}
        for note in notes:
            account_id = note.get("account_id")
            if not account_id:
                continue
            times = note_times_by_account.setdefault(account_id, [])
            times.extend(
                value
                for value in (
                    note.get("first_collected_at"),
                    note.get("last_collected_at"),
                )
                if value
            )
        creator_ids = tuple(dict.fromkeys([*account_by_id, *profile_by_id, *note_times_by_account]))
        placeholder_creators = sum(
            account_id not in account_by_id and account_id not in profile_by_id
            for account_id in creator_ids
        )
        creator_rows = []
        for account_id in creator_ids:
            account = account_by_id.get(account_id, {})
            profile = profile_by_id.get(account_id, {})
            note_times = note_times_by_account.get(account_id, [])
            first = (
                account.get("first_seen_at")
                or profile.get("collected_at")
                or (min(note_times) if note_times else "")
            )
            last = (
                account.get("last_seen_at")
                or profile.get("collected_at")
                or (max(note_times) if note_times else first)
            )
            creator_rows.append(
                (
                    "xhs",
                    account_id,
                    profile.get("nickname") or account.get("nickname") or "",
                    profile.get("red_id") or "",
                    profile.get("descr") or "",
                    profile.get("fans") or 0,
                    profile.get("follows") or 0,
                    profile.get("interaction") or 0,
                    profile.get("verify_type") if profile.get("verify_type") is not None else -1,
                    profile.get("tags") or "{}",
                    profile.get("ip_location") or "",
                    first,
                    last,
                    account.get("creator_fetched_at"),
                    profile.get("collected_at") or last,
                )
            )

        content_rows = []
        keyword_rows = []
        media_rows = []
        for note in notes:
            note_id = note["note_id"]
            content_rows.append(
                (
                    "xhs",
                    note_id,
                    "xhs",
                    note.get("account_id") or "",
                    note.get("title") or "",
                    note.get("body") or "",
                    note.get("url") or "",
                    note.get("like_count") or 0,
                    note.get("collect_count") or 0,
                    note.get("comment_count") or 0,
                    note.get("share_count") or 0,
                    note.get("published_at") or "",
                    note.get("last_collected_at") or "",
                    note.get("tags") or "[]",
                    note.get("note_type") or "",
                    note.get("video_url") or "",
                    note.get("image_urls") or "[]",
                    note.get("image_paths") or "[]",
                    note.get("raw_path") or "",
                    note.get("author_avatar") or "",
                    note.get("ip_location") or "",
                    note.get("first_collected_at") or "",
                    note.get("last_collected_at") or "",
                    self._legacy_detail_fetched(note),
                    note.get("comments_fetched_at"),
                )
            )
            for keyword in dict.fromkeys(_loads(note.get("source_keywords"), [])):
                keyword_rows.append(("xhs", note_id, keyword))
            for path in dict.fromkeys(_loads(note.get("image_paths"), [])):
                media_rows.append(("xhs", note_id, path, hashlib.sha256(path.encode()).hexdigest()))

        comment_rows = [
            (
                "xhs",
                row.get("comment_id") or "",
                row["note_id"],
                row.get("comment_key")
                or hashlib.sha256((row.get("body") or "").encode()).hexdigest(),
                row.get("body") or "",
                row.get("like_count") or 0,
                row.get("parent_comment_id") or "",
                row.get("author_id") or "",
                row.get("author_nickname") or "",
                row.get("author_avatar") or "",
                row.get("ip_location") or "",
                row.get("pictures") or "[]",
                row.get("sub_comment_count") or 0,
                row.get("created_at") or "",
                row.get("collected_at") or "",
            )
            for row in comments
        ]
        report = LegacyImportReport(
            len(creator_rows),
            len(content_rows),
            len(comment_rows),
            len(keyword_rows),
            len(media_rows),
            dry_run,
            placeholder_creators,
        )
        if dry_run:
            return report
        try:
            with self.connection.cursor() as cursor:
                self._write(
                    cursor,
                    creator_rows,
                    content_rows,
                    comment_rows,
                    keyword_rows,
                    media_rows,
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return report

    @staticmethod
    def _legacy_detail_fetched(note: dict):
        keywords = _loads(note.get("source_keywords"), [])
        images = _loads(note.get("image_paths"), [])
        if not keywords or images or note.get("comments_fetched_at"):
            return note.get("last_collected_at") or note.get("first_collected_at") or None
        return None

    @staticmethod
    def _write(cursor, creators, contents, comments, keywords, media) -> None:
        if creators:
            cursor.executemany(
                """INSERT INTO creators
                   (platform,external_id,nickname,red_id,description,fans,follows,interaction,
                    verify_type,tags,ip_location,first_seen_at,last_seen_at,creator_fetched_at,
                    updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE nickname=VALUES(nickname),red_id=VALUES(red_id),
                   description=VALUES(description),last_seen_at=VALUES(last_seen_at),
                   creator_fetched_at=VALUES(creator_fetched_at),updated_at=VALUES(updated_at)""",
                creators,
            )
        if contents:
            cursor.executemany(
                """INSERT INTO contents
                   (platform,external_id,creator_platform,creator_external_id,title,body,url,
                    like_count,collect_count,comment_count,share_count,published_at,updated_at,tags,
                    content_type,video_url,image_urls,image_paths,raw_path,author_avatar,ip_location,
                    first_seen_at,last_seen_at,detail_fetched_at,comments_fetched_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                           %s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE title=VALUES(title),body=VALUES(body),
                   like_count=VALUES(like_count),collect_count=VALUES(collect_count),
                   comment_count=VALUES(comment_count),share_count=VALUES(share_count),
                   last_seen_at=VALUES(last_seen_at),
                   detail_fetched_at=VALUES(detail_fetched_at),
                   comments_fetched_at=VALUES(comments_fetched_at)""",
                contents,
            )
        calls = (
            (
                comments,
                """INSERT INTO content_comments
                   (platform,external_id,content_external_id,comment_key,body,like_count,
                    parent_external_id,author_external_id,author_nickname,author_avatar,ip_location,
                    pictures,sub_comment_count,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE like_count=VALUES(like_count),
                   sub_comment_count=VALUES(sub_comment_count),updated_at=VALUES(updated_at)""",
            ),
            (
                keywords,
                """INSERT INTO content_keywords(platform,content_external_id,keyword)
                   VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE keyword=VALUES(keyword)""",
            ),
            (
                media,
                """INSERT INTO media_assets(platform,content_external_id,path,path_hash)
                   VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE path=VALUES(path)""",
            ),
        )
        for rows, sql in calls:
            if rows:
                cursor.executemany(sql, rows)
