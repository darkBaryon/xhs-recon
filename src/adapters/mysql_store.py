"""Store 端口的 MySQL 实现：数据入本机 MySQL 的独立库 xhs_recon。

与 uni_atlas 同一台 MySQL、同一套凭据（~/.my.cnf），但用独立 database，既能和
study_abroad 原生跨库 join（合数据做选题那步天然通），又不污染 uni_atlas 的表。

「是否已拉」= 行上的时间戳列（notes.comments_fetched_at / accounts.creator_fetched_at）。
互动数每次再遇到就刷新，不额外发请求。评论按 (note_id, 正文哈希) 去重。

构造即幂等建库建表（CREATE DATABASE/TABLE IF NOT EXISTS）。真库语义走
scripts/integration_store.py 验收，不进离线 CI（同 uni_atlas：DB 层靠真库手验）。
"""

import hashlib
import json
import os
from datetime import datetime, timedelta

import pymysql

from src.core.store import Store
from src.models import Account, Comment, CreatorProfile, Note, TypicalNote

_MYCNF = os.path.expanduser("~/.my.cnf")

# LONGTEXT 不设 DEFAULT（旧版 MySQL 不允许）——所有 INSERT 都显式给值，故无需默认。
_DDL = [
    """CREATE TABLE IF NOT EXISTS accounts (
        account_id VARCHAR(64) PRIMARY KEY,
        nickname VARCHAR(255) NOT NULL DEFAULT '',
        source_keywords LONGTEXT,
        note_count INT NOT NULL DEFAULT 0,
        first_seen_at VARCHAR(40) NOT NULL DEFAULT '',
        last_seen_at VARCHAR(40) NOT NULL DEFAULT '',
        creator_fetched_at VARCHAR(40) NULL
    ) CHARACTER SET utf8mb4""",
    """CREATE TABLE IF NOT EXISTS notes (
        note_id VARCHAR(64) PRIMARY KEY,
        account_id VARCHAR(64) NOT NULL DEFAULT '',
        title TEXT, body LONGTEXT, tags LONGTEXT, url TEXT,
        like_count INT NOT NULL DEFAULT 0,
        collect_count INT NOT NULL DEFAULT 0,
        comment_count INT NOT NULL DEFAULT 0,
        published_at VARCHAR(40) NOT NULL DEFAULT '',
        source_keywords LONGTEXT, raw_path TEXT,
        note_type VARCHAR(32) NOT NULL DEFAULT '',
        video_url TEXT,
        share_count INT NOT NULL DEFAULT 0,
        author_avatar TEXT,
        ip_location VARCHAR(64) NOT NULL DEFAULT '',
        image_urls LONGTEXT, image_paths LONGTEXT,
        first_collected_at VARCHAR(40) NOT NULL DEFAULT '',
        last_collected_at VARCHAR(40) NOT NULL DEFAULT '',
        comments_fetched_at VARCHAR(40) NULL,
        INDEX (account_id)
    ) CHARACTER SET utf8mb4""",
    # comment_key = comment_id 优先，缺则正文哈希（兼容历史四项评论）；二级评论靠
    # parent_comment_id 区分。like/sub_count 易变，ON DUPLICATE 刷新。
    """CREATE TABLE IF NOT EXISTS comments (
        note_id VARCHAR(64) NOT NULL,
        comment_key VARCHAR(64) NOT NULL,
        comment_id VARCHAR(64) NOT NULL DEFAULT '',
        parent_comment_id VARCHAR(64) NOT NULL DEFAULT '',
        body LONGTEXT,
        author_id VARCHAR(64) NOT NULL DEFAULT '',
        author_nickname VARCHAR(255) NOT NULL DEFAULT '',
        author_avatar TEXT,
        ip_location VARCHAR(64) NOT NULL DEFAULT '',
        pictures LONGTEXT,
        sub_comment_count INT NOT NULL DEFAULT 0,
        like_count INT NOT NULL DEFAULT 0,
        created_at VARCHAR(40) NOT NULL DEFAULT '',
        collected_at VARCHAR(40) NOT NULL DEFAULT '',
        PRIMARY KEY (note_id, comment_key)
    ) CHARACTER SET utf8mb4""",
    """CREATE TABLE IF NOT EXISTS creator_profiles (
        account_id VARCHAR(64) PRIMARY KEY,
        nickname VARCHAR(255) NOT NULL DEFAULT '',
        red_id VARCHAR(64) NOT NULL DEFAULT '',
        verify_type INT NOT NULL DEFAULT -1,
        descr LONGTEXT,
        fans INT NOT NULL DEFAULT 0,
        follows INT NOT NULL DEFAULT 0,
        interaction INT NOT NULL DEFAULT 0,
        tags LONGTEXT,
        ip_location VARCHAR(255) NOT NULL DEFAULT '',
        collected_at VARCHAR(40) NOT NULL DEFAULT ''
    ) CHARACTER SET utf8mb4""",
]


def _hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class MySQLStore(Store):
    def __init__(self, database: str = "xhs_recon"):
        # 先无库连接建 database（凭据自 ~/.my.cnf），再连进该库建表——都幂等
        boot = pymysql.connect(read_default_file=_MYCNF, charset="utf8mb4")
        with boot.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4")
        boot.commit()
        boot.close()

        self.conn = pymysql.connect(
            read_default_file=_MYCNF,
            database=database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        with self.conn.cursor() as cur:
            for ddl in _DDL:
                cur.execute(ddl)
        self.conn.commit()

    # ---- 写入 ----
    def upsert_accounts(self, accounts: list[Account]) -> None:
        if not accounts:
            return
        with self.conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO accounts
                     (account_id, nickname, source_keywords, note_count,
                      first_seen_at, last_seen_at)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE
                     nickname=VALUES(nickname),
                     source_keywords=VALUES(source_keywords),
                     note_count=VALUES(note_count),
                     last_seen_at=VALUES(last_seen_at)""",
                [
                    (
                        a.account_id,
                        a.nickname,
                        json.dumps(a.source_keywords, ensure_ascii=False),
                        a.note_count,
                        a.first_seen_at,
                        a.last_seen_at,
                    )
                    for a in accounts
                ],
            )
        self.conn.commit()

    def upsert_notes(self, notes: list[Note]) -> None:
        if not notes:
            return
        with self.conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO notes
                     (note_id, account_id, title, body, tags, url,
                      like_count, collect_count, comment_count, published_at,
                      source_keywords, raw_path, note_type, video_url, share_count,
                      author_avatar, ip_location, image_urls, image_paths,
                      first_collected_at, last_collected_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE
                     title=VALUES(title), body=VALUES(body), tags=VALUES(tags),
                     url=VALUES(url), like_count=VALUES(like_count),
                     collect_count=VALUES(collect_count),
                     comment_count=VALUES(comment_count),
                     source_keywords=VALUES(source_keywords), raw_path=VALUES(raw_path),
                     note_type=VALUES(note_type), video_url=VALUES(video_url),
                     share_count=VALUES(share_count), author_avatar=VALUES(author_avatar),
                     ip_location=VALUES(ip_location), image_urls=VALUES(image_urls),
                     image_paths=VALUES(image_paths),
                     last_collected_at=VALUES(last_collected_at)""",
                # first_collected_at 不在 UPDATE 列表 → 已存在时保留原值（幂等关键）；
                # comments_fetched_at 不插不更 → 保留（不因再遇到而清空）。
                # image_paths 空列表时 UPDATE 会覆盖：B 阶段下载后单独回填，此处灌 URL 层不清空——
                # 故仅当新值非空才该覆盖；用 COALESCE 逻辑留待 B 阶段，A 阶段 image_paths 恒空。
                [
                    (
                        n.note_id,
                        n.account_id,
                        n.title,
                        n.body,
                        json.dumps(n.tags, ensure_ascii=False),
                        n.url,
                        n.like_count,
                        n.collect_count,
                        n.comment_count,
                        n.published_at,
                        json.dumps(n.source_keywords, ensure_ascii=False),
                        n.raw_path,
                        n.note_type,
                        n.video_url,
                        n.share_count,
                        n.author_avatar,
                        n.ip_location,
                        json.dumps(n.image_urls, ensure_ascii=False),
                        json.dumps(n.image_paths, ensure_ascii=False),
                        n.collected_at,
                        n.collected_at,
                    )
                    for n in notes
                ],
            )
        self.conn.commit()

    def upsert_comments(self, comments: list[Comment]) -> None:
        if not comments:
            return
        with self.conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO comments
                     (note_id, comment_key, comment_id, parent_comment_id, body,
                      author_id, author_nickname, author_avatar, ip_location, pictures,
                      sub_comment_count, like_count, created_at, collected_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE
                     like_count=VALUES(like_count),
                     sub_comment_count=VALUES(sub_comment_count)""",
                [
                    (
                        c.note_id,
                        c.comment_id or _hash(c.body),
                        c.comment_id,
                        c.parent_comment_id,
                        c.body,
                        c.author_id,
                        c.author_nickname,
                        c.author_avatar,
                        c.ip_location,
                        json.dumps(c.pictures, ensure_ascii=False),
                        c.sub_comment_count,
                        c.like_count,
                        c.created_at,
                        c.collected_at,
                    )
                    for c in comments
                ],
            )
        self.conn.commit()

    def upsert_profiles(self, profiles: list[CreatorProfile]) -> None:
        if not profiles:
            return
        with self.conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO creator_profiles
                     (account_id, nickname, red_id, verify_type, descr, fans,
                      follows, interaction, tags, ip_location, collected_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE
                     nickname=VALUES(nickname), red_id=VALUES(red_id),
                     verify_type=VALUES(verify_type), descr=VALUES(descr),
                     fans=VALUES(fans), follows=VALUES(follows),
                     interaction=VALUES(interaction), tags=VALUES(tags),
                     ip_location=VALUES(ip_location), collected_at=VALUES(collected_at)""",
                [
                    (
                        p.account_id,
                        p.nickname,
                        p.red_id,
                        p.verify_type,
                        p.desc,
                        p.fans,
                        p.follows,
                        p.interaction,
                        json.dumps(p.tags, ensure_ascii=False),
                        p.ip_location,
                        p.collected_at,
                    )
                    for p in profiles
                ],
            )
        self.conn.commit()

    # ---- 抓取状态标记 ----
    def mark_comments_fetched(self, note_ids: list[str], at: str) -> None:
        if not note_ids:
            return
        with self.conn.cursor() as cur:
            cur.executemany(
                "UPDATE notes SET comments_fetched_at=%s WHERE note_id=%s",
                [(at, nid) for nid in note_ids],
            )
        self.conn.commit()

    def mark_creator_fetched(self, account_ids: list[str], at: str) -> None:
        if not account_ids:
            return
        with self.conn.cursor() as cur:
            cur.executemany(
                "UPDATE accounts SET creator_fetched_at=%s WHERE account_id=%s",
                [(at, aid) for aid in account_ids],
            )
        self.conn.commit()

    # ---- 增量判据 / 读取 ----
    def known_note_ids(self) -> set[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT note_id FROM notes")
            return {r["note_id"] for r in cur.fetchall()}

    def notes_needing_comments(
        self, candidates: list[TypicalNote], refresh_days: int, now_iso: str
    ) -> list[TypicalNote]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT note_id, comments_fetched_at FROM notes "
                "WHERE comments_fetched_at IS NOT NULL"
            )
            fetched = {r["note_id"]: r["comments_fetched_at"] for r in cur.fetchall()}
        cutoff = None
        if refresh_days > 0:
            cutoff = datetime.fromisoformat(now_iso) - timedelta(days=refresh_days)
        out = []
        for c in candidates:
            at = fetched.get(c.note_id)
            if at is None:  # 从没抓过评论 → 要抓
                out.append(c)
            elif cutoff is not None and _before(at, cutoff):  # 抓过但过期 → 刷新
                out.append(c)
        return out

    def load_notes(self) -> list[Note]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM notes")
            rows = cur.fetchall()
        return [
            Note(
                note_id=r["note_id"],
                account_id=r["account_id"],
                title=r["title"] or "",
                body=r["body"] or "",
                tags=json.loads(r["tags"] or "[]"),
                url=r["url"] or "",
                like_count=r["like_count"],
                collect_count=r["collect_count"],
                comment_count=r["comment_count"],
                published_at=r["published_at"],
                collected_at=r["last_collected_at"],
                source_keywords=json.loads(r["source_keywords"] or "[]"),
                raw_path=r["raw_path"] or "",
                note_type=r["note_type"] or "",
                video_url=r["video_url"] or "",
                share_count=r["share_count"],
                author_avatar=r["author_avatar"] or "",
                ip_location=r["ip_location"] or "",
                image_urls=json.loads(r["image_urls"] or "[]"),
                image_paths=json.loads(r["image_paths"] or "[]"),
            )
            for r in rows
        ]

    def load_accounts(self) -> list[Account]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM accounts")
            rows = cur.fetchall()
        return [
            Account(
                account_id=r["account_id"],
                nickname=r["nickname"],
                source_keywords=json.loads(r["source_keywords"] or "[]"),
                note_count=r["note_count"],
                first_seen_at=r["first_seen_at"],
                last_seen_at=r["last_seen_at"],
            )
            for r in rows
        ]

    def close(self) -> None:
        self.conn.close()


def _before(iso_at: str, cutoff: datetime) -> bool:
    """iso_at 早于 cutoff？解析失败（脏时间）当作「过期需刷新」返回 True。"""
    try:
        return datetime.fromisoformat(iso_at) < cutoff
    except ValueError:
        return True
