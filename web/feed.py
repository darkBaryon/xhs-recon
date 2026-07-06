"""把 MySQL 全库（notes/comments/accounts/creator_profiles）装成小红书风格本地站。

与旧 report（读单次运行导出 CSV）不同：feed 读的是**累计全库**——每次运行增量入库，
这里一次装出全部帖子 + 评论 + 账号，做成离线可开的「本地小红书」。

前后端分离同旧约定：Python 只负责「读库 → 拼 payload → 写 data.js + 拷静态资源」，
渲染全在 app.js。图片引用 media 持久图库的相对路径（site 与 media 同在 data/ 下），
远程 CDN 图只做兜底（带签名会过期）。纯函数（行→payload）与 DB 读取分离，便于测试。
"""

import json
import shutil
from pathlib import Path

_STATIC_ASSETS = ("index.html", "style.css", "app.js")
_WEB_DIR = Path(__file__).parent


def _loads(value, default):
    try:
        parsed = json.loads(value) if value else default
    except (TypeError, ValueError):
        return default
    return parsed if isinstance(parsed, type(default)) else default


def _rel_media_paths(image_paths: str, site_dir: Path) -> list[str]:
    """库里存的是 media 图库绝对路径；site 在 data/site → 相对引用 ../media/...。

    路径不含 /data/media/ 或文件已不存在的跳过（挪过目录的历史数据）。"""
    rels = []
    for p in _loads(image_paths, []):
        marker = "/data/media/"
        idx = str(p).find(marker)
        if idx < 0 or not Path(p).exists():
            continue
        rels.append("../media/" + str(p)[idx + len(marker) :])
    return rels


def norm_note(row: dict, site_dir: Path) -> dict:
    imgs = _rel_media_paths(row.get("image_paths") or "", site_dir)
    remote = _loads(row.get("image_urls") or "", [])
    return {
        "id": row.get("note_id", ""),
        "aid": row.get("account_id", ""),
        "author": row.get("nickname") or "未知作者",
        "avatar": row.get("author_avatar") or "",
        "title": row.get("title") or "",
        "body": row.get("body") or "",
        "tags": _loads(row.get("tags") or "", []),
        "url": row.get("url") or "",
        "like": int(row.get("like_count") or 0),
        "collect": int(row.get("collect_count") or 0),
        "comment": int(row.get("comment_count") or 0),
        "date": (row.get("published_at") or "")[:10],
        "video": bool(row.get("video_url")),
        "imgs": imgs,
        # 本地图缺失时的兜底封面（CDN 签名会过期，能显多久算多久）
        "cover_remote": remote[0] if (not imgs and remote) else "",
        "ip": row.get("ip_location") or "",
    }


def norm_comment(row: dict) -> dict:
    return {
        "id": row.get("comment_id") or row.get("comment_key") or "",
        "nid": row.get("note_id", ""),
        "parent": row.get("parent_comment_id") or "",
        "author": row.get("author_nickname") or "匿名",
        "avatar": row.get("author_avatar") or "",
        "body": row.get("body") or "",
        "like": int(row.get("like_count") or 0),
        "date": (row.get("created_at") or "")[:10],
        "ip": row.get("ip_location") or "",
    }


def assemble(
    note_rows: list[dict], comment_rows: list[dict], profile_rows: list[dict], site_dir: Path
) -> dict:
    notes = [norm_note(r, site_dir) for r in note_rows]
    comments = [norm_comment(r) for r in comment_rows]
    profiles = {
        r["account_id"]: {
            "fans": int(r.get("fans") or 0),
            "descr": r.get("descr") or "",
            "red_id": r.get("red_id") or "",
            "verify": int(r.get("verify_type") or -1),
        }
        for r in profile_rows
    }
    # 账号列表由笔记聚合（有帖才值得点），档案有则并入
    by_acc: dict[str, dict] = {}
    for n in notes:
        acc = by_acc.setdefault(
            n["aid"], {"aid": n["aid"], "nick": n["author"], "avatar": n["avatar"], "notes": 0}
        )
        acc["notes"] += 1
        if not acc["avatar"] and n["avatar"]:
            acc["avatar"] = n["avatar"]
    for aid, prof in profiles.items():
        if aid in by_acc:
            by_acc[aid].update(prof)
    accounts = sorted(by_acc.values(), key=lambda a: -a["notes"])
    return {"notes": notes, "comments": comments, "accounts": accounts}


def _fetch_all(conn, sql: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql)
        return list(cur.fetchall())


def build_feed(site_dir: Path, database: str = "xhs_recon") -> Path:
    """读全库 → data.js + 静态资源 → site_dir/index.html（返回入口路径）。"""
    import pymysql

    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    conn = pymysql.connect(
        read_default_file=str(Path("~/.my.cnf").expanduser()),
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        note_rows = _fetch_all(
            conn,
            "SELECT n.*, a.nickname FROM notes n LEFT JOIN accounts a"
            " ON n.account_id = a.account_id ORDER BY n.published_at DESC",
        )
        comment_rows = _fetch_all(conn, "SELECT * FROM comments ORDER BY created_at")
        profile_rows = _fetch_all(conn, "SELECT * FROM creator_profiles")
    finally:
        conn.close()

    payload = assemble(note_rows, comment_rows, profile_rows, site_dir)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (site_dir / "data.js").write_text(f"window.FEED_DATA = {data};", encoding="utf-8")
    for name in _STATIC_ASSETS:
        shutil.copy(_WEB_DIR / name, site_dir / name)
    return site_dir / "index.html"
