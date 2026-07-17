import hashlib
import json
import os
import re
from datetime import datetime, timedelta

import pymysql

from ....domain.content import (
    AccountCollectionResult,
    ContentReference,
    SearchCollectionResult,
)
from ....domain.identity import EntityId, PlatformId

_MYCNF = os.path.expanduser("~/.my.cnf")
_DATABASE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

_MIGRATE_COLUMNS = {
    "contents": (
        ("author_avatar", "TEXT"),
        ("ip_location", "VARCHAR(255) NOT NULL DEFAULT ''"),
        ("detail_fetched_at", "VARCHAR(40) NULL"),
        ("comments_fetched_at", "VARCHAR(40) NULL"),
    ),
    "content_comments": (
        ("author_avatar", "TEXT"),
        ("ip_location", "VARCHAR(255) NOT NULL DEFAULT ''"),
        ("pictures", "LONGTEXT"),
        ("sub_comment_count", "BIGINT NOT NULL DEFAULT 0"),
    ),
}

_DDL = (
    """CREATE TABLE IF NOT EXISTS creators (
        platform VARCHAR(32) NOT NULL,
        external_id VARCHAR(128) NOT NULL,
        nickname VARCHAR(255) NOT NULL DEFAULT '',
        red_id VARCHAR(128) NOT NULL DEFAULT '',
        description LONGTEXT,
        fans BIGINT NOT NULL DEFAULT 0,
        follows BIGINT NOT NULL DEFAULT 0,
        interaction BIGINT NOT NULL DEFAULT 0,
        verify_type INT NOT NULL DEFAULT -1,
        tags LONGTEXT,
        ip_location VARCHAR(255) NOT NULL DEFAULT '',
        first_seen_at VARCHAR(40) NOT NULL DEFAULT '',
        last_seen_at VARCHAR(40) NOT NULL DEFAULT '',
        creator_fetched_at VARCHAR(40) NULL,
        updated_at VARCHAR(40) NOT NULL DEFAULT '',
        PRIMARY KEY(platform, external_id)
    ) CHARACTER SET utf8mb4""",
    """CREATE TABLE IF NOT EXISTS contents (
        platform VARCHAR(32) NOT NULL,
        external_id VARCHAR(128) NOT NULL,
        creator_platform VARCHAR(32) NOT NULL,
        creator_external_id VARCHAR(128) NOT NULL,
        title TEXT, body LONGTEXT, url TEXT,
        like_count BIGINT NOT NULL DEFAULT 0,
        collect_count BIGINT NOT NULL DEFAULT 0,
        comment_count BIGINT NOT NULL DEFAULT 0,
        share_count BIGINT NOT NULL DEFAULT 0,
        published_at VARCHAR(40) NOT NULL DEFAULT '',
        updated_at VARCHAR(40) NOT NULL DEFAULT '',
        tags LONGTEXT,
        content_type VARCHAR(32) NOT NULL DEFAULT '',
        video_url TEXT,
        image_urls LONGTEXT,
        image_paths LONGTEXT,
        raw_path TEXT,
        author_avatar TEXT,
        ip_location VARCHAR(255) NOT NULL DEFAULT '',
        first_seen_at VARCHAR(40) NOT NULL DEFAULT '',
        last_seen_at VARCHAR(40) NOT NULL DEFAULT '',
        detail_fetched_at VARCHAR(40) NULL,
        comments_fetched_at VARCHAR(40) NULL,
        PRIMARY KEY(platform, external_id),
        INDEX creator_idx(creator_platform, creator_external_id)
    ) CHARACTER SET utf8mb4""",
    """CREATE TABLE IF NOT EXISTS content_comments (
        platform VARCHAR(32) NOT NULL,
        external_id VARCHAR(128) NOT NULL,
        content_external_id VARCHAR(128) NOT NULL,
        comment_key VARCHAR(128) NOT NULL,
        body LONGTEXT,
        like_count BIGINT NOT NULL DEFAULT 0,
        parent_external_id VARCHAR(128) NOT NULL DEFAULT '',
        author_external_id VARCHAR(128) NOT NULL DEFAULT '',
        author_nickname VARCHAR(255) NOT NULL DEFAULT '',
        author_avatar TEXT,
        ip_location VARCHAR(255) NOT NULL DEFAULT '',
        pictures LONGTEXT,
        sub_comment_count BIGINT NOT NULL DEFAULT 0,
        created_at VARCHAR(40) NOT NULL DEFAULT '',
        updated_at VARCHAR(40) NOT NULL DEFAULT '',
        PRIMARY KEY(platform, content_external_id, comment_key),
        INDEX external_id_idx(platform, external_id)
    ) CHARACTER SET utf8mb4""",
    """CREATE TABLE IF NOT EXISTS media_assets (
        platform VARCHAR(32) NOT NULL,
        content_external_id VARCHAR(128) NOT NULL,
        path TEXT NOT NULL,
        path_hash CHAR(64) NOT NULL,
        PRIMARY KEY(platform, content_external_id, path_hash)
    ) CHARACTER SET utf8mb4""",
    """CREATE TABLE IF NOT EXISTS content_keywords (
        platform VARCHAR(32) NOT NULL,
        content_external_id VARCHAR(128) NOT NULL,
        keyword VARCHAR(255) NOT NULL,
        PRIMARY KEY(platform, content_external_id, keyword)
    ) CHARACTER SET utf8mb4""",
)


def connect_existing_database(database: str):
    """连接既有数据库，不创建数据库、表或列。供只读迁移检查使用。"""
    if not _DATABASE_NAME.fullmatch(database):
        raise ValueError(f"invalid MySQL database name: {database!r}")
    return pymysql.connect(
        read_default_file=_MYCNF,
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


class MySQLResearchRepository:
    def __init__(self, database: str = "xhs_recon") -> None:
        if not _DATABASE_NAME.fullmatch(database):
            raise ValueError(f"invalid MySQL database name: {database!r}")
        boot = pymysql.connect(read_default_file=_MYCNF, charset="utf8mb4")
        with boot.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4")
        boot.commit()
        boot.close()
        self.connection = pymysql.connect(
            read_default_file=_MYCNF,
            database=database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        with self.connection.cursor() as cursor:
            for ddl in _DDL:
                cursor.execute(ddl)
        self._ensure_columns(database)
        self.connection.commit()

    def _ensure_columns(self, database: str) -> None:
        with self.connection.cursor() as cursor:
            for table, columns in _MIGRATE_COLUMNS.items():
                cursor.execute(
                    "SELECT COLUMN_NAME AS name FROM information_schema.columns "
                    "WHERE table_schema=%s AND table_name=%s",
                    (database, table),
                )
                existing = {row["name"] for row in cursor.fetchall()}
                for name, ddl in columns:
                    if name not in existing:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def save(self, result: AccountCollectionResult) -> None:
        self._save(result, mark_creator_fetched=True, mark_details_fetched=True)

    def save_search(self, result: SearchCollectionResult) -> None:
        self._save(result, keyword=result.keyword)

    def due_targets(self, targets, collected_at: str, refresh_days: int, batch_size: int):
        if not targets:
            return ()
        ids = [target.id.external_id for target in targets]
        placeholders = ",".join(["%s"] * len(ids))
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"SELECT external_id,creator_fetched_at FROM creators "
                f"WHERE platform=%s AND external_id IN ({placeholders})",
                [targets[0].id.platform.value, *ids],
            )
            fetched = {row["external_id"]: row["creator_fetched_at"] for row in cursor.fetchall()}
        cutoff = None
        if refresh_days > 0:
            cutoff = datetime.fromisoformat(collected_at.replace("Z", "+00:00")) - timedelta(
                days=refresh_days
            )
        due = []
        for target in targets:
            value = fetched.get(target.id.external_id)
            if not value:
                due.append(("", target))
                continue
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if cutoff is None or parsed < cutoff:
                due.append((str(value), target))
        due.sort(key=lambda item: item[0])
        selected = tuple(target for _, target in due)
        selected = selected if batch_size <= 0 else selected[:batch_size]
        selected_ids = {target.id for target in selected}
        # 旧入口约定 self 账号每批都检查，且不占普通轮转名额。
        return tuple(
            target for target in targets if target.id in selected_ids or target.source == "self"
        )

    def known_content_ids(self, target):
        with self.connection.cursor() as cursor:
            cursor.execute(
                """SELECT external_id FROM contents
                   WHERE creator_platform=%s AND creator_external_id=%s
                   AND detail_fetched_at IS NOT NULL""",
                (target.id.platform.value, target.id.external_id),
            )
            return frozenset(row["external_id"] for row in cursor.fetchall())

    def content_ids_needing_comments(self, target, collected_at, refresh_days):
        with self.connection.cursor() as cursor:
            cursor.execute(
                """SELECT external_id,comments_fetched_at FROM contents
                   WHERE creator_platform=%s AND creator_external_id=%s
                   AND detail_fetched_at IS NOT NULL""",
                (target.id.platform.value, target.id.external_id),
            )
            rows = cursor.fetchall()
        cutoff = None
        if refresh_days > 0:
            cutoff = datetime.fromisoformat(collected_at.replace("Z", "+00:00")) - timedelta(
                days=refresh_days
            )
        return frozenset(
            row["external_id"]
            for row in rows
            if not row["comments_fetched_at"]
            or (
                cutoff is not None
                and datetime.fromisoformat(str(row["comments_fetched_at"]).replace("Z", "+00:00"))
                < cutoff
            )
        )

    def save_watchlist(self, result: AccountCollectionResult, *, comments_fetched: bool) -> None:
        self._save(
            result,
            mark_creator_fetched=not result.failures,
            mark_details_fetched=not result.failures,
            mark_comments_fetched=comments_fetched and not result.failures,
        )

    def contents_missing_media(self, limit: int) -> tuple[ContentReference, ...]:
        sql = (
            "SELECT platform,external_id,creator_platform,creator_external_id,url FROM contents "
            "WHERE (image_paths='[]' OR image_paths IS NULL OR image_paths='') "
            "AND url LIKE '%%xsec_token%%' ORDER BY published_at DESC"
        )
        if limit > 0:
            sql += f" LIMIT {int(limit)}"
        with self.connection.cursor() as cursor:
            cursor.execute(sql)
            return tuple(
                ContentReference(
                    EntityId(PlatformId(row["platform"]), row["external_id"]),
                    row["url"],
                    EntityId(
                        PlatformId(row["creator_platform"]),
                        row["creator_external_id"],
                    ),
                )
                for row in cursor.fetchall()
            )

    def save_backfill(self, result: AccountCollectionResult) -> None:
        self._save(result, mark_details_fetched=True)

    def _save(
        self,
        result: AccountCollectionResult | SearchCollectionResult,
        *,
        keyword: str | None = None,
        mark_creator_fetched: bool = False,
        mark_details_fetched: bool = False,
        mark_comments_fetched: bool = False,
    ) -> None:
        try:
            with self.connection.cursor() as cursor:
                if result.creators:
                    cursor.executemany(
                        """INSERT INTO creators
                           (platform,external_id,nickname,red_id,description,fans,follows,
                            interaction,verify_type,tags,ip_location,first_seen_at,last_seen_at,
                            creator_fetched_at,updated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON DUPLICATE KEY UPDATE nickname=VALUES(nickname),
                           red_id=VALUES(red_id),description=VALUES(description),fans=VALUES(fans),
                           follows=VALUES(follows),interaction=VALUES(interaction),
                           verify_type=VALUES(verify_type),tags=VALUES(tags),
                           ip_location=VALUES(ip_location),last_seen_at=VALUES(last_seen_at),
                           creator_fetched_at=COALESCE(
                               VALUES(creator_fetched_at),creator_fetched_at
                           ),
                           updated_at=VALUES(updated_at)""",
                        [
                            (
                                c.id.platform.value,
                                c.id.external_id,
                                c.nickname,
                                c.red_id,
                                c.description,
                                c.fans,
                                c.follows,
                                c.interaction,
                                c.verify_type,
                                json.dumps(dict(c.tags), ensure_ascii=False),
                                c.ip_location,
                                result.collected_at,
                                result.collected_at,
                                result.collected_at if mark_creator_fetched else None,
                                c.updated_at,
                            )
                            for c in result.creators
                        ],
                    )
                if result.contents:
                    cursor.executemany(
                        """INSERT INTO contents
                           (platform,external_id,creator_platform,creator_external_id,title,body,
                            url,like_count,collect_count,comment_count,share_count,published_at,
                            updated_at,tags,content_type,video_url,image_urls,image_paths,raw_path,
                            author_avatar,ip_location,first_seen_at,last_seen_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                   %s,%s,%s,%s)
                           ON DUPLICATE KEY UPDATE creator_platform=VALUES(creator_platform),
                           creator_external_id=VALUES(creator_external_id),title=VALUES(title),
                           body=VALUES(body),url=VALUES(url),like_count=VALUES(like_count),
                           collect_count=VALUES(collect_count),comment_count=VALUES(comment_count),
                           share_count=VALUES(share_count),published_at=VALUES(published_at),
                           updated_at=VALUES(updated_at),tags=VALUES(tags),
                           content_type=VALUES(content_type),video_url=VALUES(video_url),
                           image_urls=VALUES(image_urls),
                           image_paths=IF(VALUES(image_paths)='[]',image_paths,VALUES(image_paths)),
                           raw_path=VALUES(raw_path),author_avatar=VALUES(author_avatar),
                           ip_location=VALUES(ip_location),last_seen_at=VALUES(last_seen_at)""",
                        [
                            (
                                c.id.platform.value,
                                c.id.external_id,
                                c.creator_id.platform.value,
                                c.creator_id.external_id,
                                c.title,
                                c.body,
                                c.url,
                                c.engagement.likes,
                                c.engagement.collects,
                                c.engagement.comments,
                                c.engagement.shares,
                                c.published_at,
                                c.updated_at,
                                json.dumps(c.tags, ensure_ascii=False),
                                c.content_type,
                                c.video_url,
                                json.dumps(c.image_urls, ensure_ascii=False),
                                json.dumps(c.image_paths, ensure_ascii=False),
                                c.raw_path,
                                c.author_avatar,
                                c.ip_location,
                                result.collected_at,
                                result.collected_at,
                            )
                            for c in result.contents
                        ],
                    )
                comments = getattr(result, "comments", ())
                if comments:
                    cursor.executemany(
                        """INSERT INTO content_comments
                           (platform,external_id,content_external_id,comment_key,body,
                            like_count,parent_external_id,author_external_id,author_nickname,
                            author_avatar,ip_location,pictures,sub_comment_count,created_at,updated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON DUPLICATE KEY UPDATE body=VALUES(body),like_count=VALUES(like_count),
                           parent_external_id=VALUES(parent_external_id),
                           author_external_id=VALUES(author_external_id),
                           author_nickname=VALUES(author_nickname),
                           author_avatar=VALUES(author_avatar),ip_location=VALUES(ip_location),
                           pictures=VALUES(pictures),sub_comment_count=VALUES(sub_comment_count),
                           created_at=VALUES(created_at),
                           updated_at=VALUES(updated_at)""",
                        [
                            (
                                c.id.platform.value,
                                c.id.external_id,
                                c.content_id.external_id,
                                c.id.external_id
                                or hashlib.sha256(c.body.encode("utf-8")).hexdigest(),
                                c.body,
                                c.likes,
                                c.parent_external_id,
                                c.author_external_id,
                                c.author_nickname,
                                c.author_avatar,
                                c.ip_location,
                                json.dumps(c.pictures, ensure_ascii=False),
                                c.sub_comment_count,
                                c.created_at,
                                c.updated_at,
                            )
                            for c in comments
                        ],
                    )
                media_rows = [
                    (
                        content.id.platform.value,
                        content.id.external_id,
                        path,
                        hashlib.sha256(path.encode("utf-8")).hexdigest(),
                    )
                    for content in result.contents
                    for path in content.image_paths
                ]
                if media_rows:
                    cursor.executemany(
                        """INSERT INTO media_assets
                           (platform,content_external_id,path,path_hash) VALUES (%s,%s,%s,%s)
                           ON DUPLICATE KEY UPDATE path=VALUES(path)""",
                        media_rows,
                    )
                if keyword and result.contents:
                    cursor.executemany(
                        """INSERT INTO content_keywords
                           (platform,content_external_id,keyword) VALUES (%s,%s,%s)
                           ON DUPLICATE KEY UPDATE keyword=VALUES(keyword)""",
                        [
                            (content.id.platform.value, content.id.external_id, keyword)
                            for content in result.contents
                        ],
                    )
                if mark_comments_fetched and result.contents:
                    cursor.executemany(
                        """UPDATE contents SET comments_fetched_at=%s
                           WHERE platform=%s AND external_id=%s""",
                        [
                            (
                                result.collected_at,
                                content.id.platform.value,
                                content.id.external_id,
                            )
                            for content in result.contents
                        ],
                    )
                if mark_details_fetched and result.contents:
                    cursor.executemany(
                        """UPDATE contents SET detail_fetched_at=%s
                           WHERE platform=%s AND external_id=%s""",
                        [
                            (
                                result.collected_at,
                                content.id.platform.value,
                                content.id.external_id,
                            )
                            for content in result.contents
                        ],
                    )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def close(self) -> None:
        self.connection.close()


# 期1 对外名保留，避免账号接口和既有测试在期2被无意义打断。
MySQLAccountRepository = MySQLResearchRepository
