#!/usr/bin/env python3
"""MySQLStore 真库验收（手动集成，不进离线 CI）。

同 uni_atlas：DB 层不写离线单测，靠对真实本机 MySQL 跑一遍验收。用一个一次性测试库
（默认 xhs_recon_itest）建/删，覆盖：幂等 upsert、评论去重、增量评论判据、refresh 窗、
落库往返。全绿打印 OK，任一 assert 失败即非零退出。

用法:  uv run python scripts/integration_store.py [测试库名=xhs_recon_itest]
"""

import os
import sys
from pathlib import Path

import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.adapters.mysql_store import MySQLStore  # noqa: E402
from src.models import Account, Comment, CreatorProfile, Note, TypicalNote  # noqa: E402


def _note(nid, collected_at, like=10, body="正文"):
    return Note(
        note_id=nid,
        account_id="U1",
        title=f"标题{nid}",
        body=body,
        tags=["留学"],
        url=f"http://x/{nid}",
        like_count=like,
        collect_count=1,
        comment_count=2,
        published_at="2026-07-01T00:00:00+00:00",
        collected_at=collected_at,
        source_keywords=["留学辅导"],
        raw_path="p",
    )


def _typical(nid):
    return TypicalNote(
        account_id="U1",
        note_id=nid,
        title=f"标题{nid}",
        url=f"http://x/{nid}",
        note_score=1.0,
        selection_reason="t",
    )


def _drop(db):
    conn = pymysql.connect(read_default_file=os.path.expanduser("~/.my.cnf"), charset="utf8mb4")
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS `{db}`")
    conn.commit()
    conn.close()


def run(db):
    _drop(db)  # 干净起步
    s = MySQLStore(db)

    # 1) 幂等 upsert + first_collected_at 不回改 + 易变字段刷新
    s.upsert_notes([_note("N1", "2026-07-01T00:00:00+00:00", like=10)])
    s.upsert_notes([_note("N1", "2026-07-05T00:00:00+00:00", like=999)])
    with s.conn.cursor() as cur:
        cur.execute("SELECT like_count, first_collected_at, last_collected_at FROM notes")
        r = cur.fetchone()
    assert s.known_note_ids() == {"N1"}, "note 未去重"
    assert r["like_count"] == 999, "易变字段未刷新"
    assert r["first_collected_at"] == "2026-07-01T00:00:00+00:00", "first_collected_at 被回改"
    assert r["last_collected_at"] == "2026-07-05T00:00:00+00:00", "last_collected_at 未刷新"
    print("  ✓ 幂等 upsert / first 保留 / 易变刷新")

    # 1b) image_paths 空不覆盖：creator 下图后，search（恒 []）再遇同帖不得冲掉
    n_img = _note("N1", "2026-07-06T00:00:00+00:00")
    n_img.image_paths = ["/raw/xhs/images/N1/0.jpg"]
    s.upsert_notes([n_img])
    s.upsert_notes([_note("N1", "2026-07-07T00:00:00+00:00")])  # image_paths=[]
    with s.conn.cursor() as cur:
        cur.execute("SELECT image_paths FROM notes WHERE note_id='N1'")
        assert "0.jpg" in cur.fetchone()["image_paths"], "空 image_paths 覆盖了已下载图路径"
    print("  ✓ image_paths 空不覆盖（search 不冲掉 creator 已下的图）")

    # 2) 评论按 (note_id, 正文哈希) 去重
    dup = Comment(body="同一句", note_id="N1", like_count=3, collected_at="2026-07-05")
    s.upsert_comments([dup, dup])
    s.upsert_comments([Comment(body="同一句", note_id="N1", like_count=99, collected_at="x")])
    s.upsert_comments([Comment(body="同一句", note_id="N2", like_count=1, collected_at="x")])
    with s.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) c FROM comments")
        assert cur.fetchone()["c"] == 2, "评论去重失败"
    print("  ✓ 评论 (note_id, 正文哈希) 去重")

    # 3) 增量评论判据 + 标记
    s.upsert_notes([_note("N2", "2026-07-01T00:00:00+00:00")])
    cands = [_typical("N1"), _typical("N2")]
    now = "2026-07-06T00:00:00+00:00"
    assert {t.note_id for t in s.notes_needing_comments(cands, 7, now)} == {"N1", "N2"}
    s.mark_comments_fetched(["N1"], "2026-07-06T00:00:00+00:00")
    assert {t.note_id for t in s.notes_needing_comments(cands, 7, now)} == {"N2"}
    print("  ✓ 增量：已抓跳过、未抓保留")

    # 4) refresh 窗
    s.mark_comments_fetched(["N2"], "2026-07-01T00:00:00+00:00")  # 5 天前
    assert s.notes_needing_comments([_typical("N2")], 7, now) == [], "7天窗内不应重抓"
    assert {t.note_id for t in s.notes_needing_comments([_typical("N2")], 3, now)} == {"N2"}
    assert s.notes_needing_comments([_typical("N2")], 0, now) == [], "refresh=0 只抓从没抓过的"
    print("  ✓ refresh 窗（7 不抓 / 3 重抓 / 0 不抓）")

    # 5) 落库往返 + 档案 + creator 标记
    s.upsert_accounts(
        [
            Account(
                account_id="U1",
                nickname="甲",
                source_keywords=["留学辅导"],
                note_count=3,
                first_seen_at="x",
                last_seen_at="x",
            )
        ]
    )
    s.mark_creator_fetched(["U1"], "2026-07-06T00:00:00+00:00")
    s.upsert_profiles(
        [
            CreatorProfile(
                account_id="U1",
                nickname="甲",
                verify_type=2,
                fans=1000,
                desc="简介",
                collected_at="x",
            )
        ]
    )
    notes = s.load_notes()
    # like=10：1b 步骤最后一次 upsert 的值（易变字段随最近一次刷新）
    assert any(n.note_id == "N1" and n.like_count == 10 and n.tags == ["留学"] for n in notes)
    assert any(n.image_paths == ["/raw/xhs/images/N1/0.jpg"] for n in notes), "图路径往返失败"
    assert s.load_accounts()[0].note_count == 3
    with s.conn.cursor() as cur:
        cur.execute("SELECT creator_fetched_at FROM accounts WHERE account_id='U1'")
        assert cur.fetchone()["creator_fetched_at"] == "2026-07-06T00:00:00+00:00"
        cur.execute("SELECT verify_type, descr FROM creator_profiles WHERE account_id='U1'")
        p = cur.fetchone()
        assert p["verify_type"] == 2 and p["descr"] == "简介"
    print("  ✓ 落库往返 / creator 标记 / 档案")

    s.close()
    _drop(db)  # 清理


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else "xhs_recon_itest"
    print(f"MySQLStore 真库验收（测试库 {db}）：")
    run(db)
    print("OK：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
