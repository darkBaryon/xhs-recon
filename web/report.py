"""把一次运行目录的导出装成前端数据，落成自包含静态站（离线 file:// 可开）。

只读导出文件、不依赖 core/models，对搜索侧（account_rank/notes）与 sync 侧
（watchlist/creator_profiles/account_profile/topic_feed）都稳健：缺哪个文件就少哪块，
不报错。

前后端分离：本模块只负责「读导出 → 拼 payload → 写 data.js」，并把 web/ 下手写的
index.html/style.css/app.js 原样拷进运行目录。渲染全在 app.js（原生 JS）。
Python 不再拼任何 HTML。data.js 以 <script src> 加载，file:// 下无跨域限制、双击即开。
"""

import csv
import json
import shutil
from pathlib import Path

# 手写静态资源：跟着运行目录一起拷贝，令该目录自包含可开
_STATIC_ASSETS = ("index.html", "style.css", "app.js")

PIPE = "|"


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _int(v) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0


def _float(v) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _norm_note(row: dict, *, from_jsonl: bool) -> dict:
    tags = row.get("tags") or []
    if not from_jsonl:  # notes.csv 的 tags 是 | 连接串
        tags = [t for t in str(tags).split(PIPE) if t]
    return {
        "title": row.get("title", ""),
        "url": row.get("url", ""),
        "date": (row.get("published_at") or "")[:10],
        "like": _int(row.get("like_count")),
        "collect": _int(row.get("collect_count")),
        "comment": _int(row.get("comment_count")),
        "tags": tags[:6],
    }


def _eng(n: dict) -> int:
    return n["like"] + n["collect"] + n["comment"]


def assemble(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    watch = _read_csv(run_dir / "watchlist.csv")
    ranks = _read_csv(run_dir / "account_rank.csv")
    prof = {r["account_id"]: r for r in _read_csv(run_dir / "account_profile.csv")}
    cre = {r["account_id"]: r for r in _read_csv(run_dir / "creator_profiles.csv")}
    rankmap = {r["account_id"]: r for r in ranks}
    tf = _read_jsonl(run_dir / "topic_feed.jsonl")
    notes_csv = _read_csv(run_dir / "notes.csv")

    # 每账号笔记：优先 topic_feed（窗内），否则退回全量 notes.csv
    from_jsonl = bool(tf)
    note_source = tf if tf else notes_csv
    notes_by_acc: dict[str, list[dict]] = {}
    for row in note_source:
        notes_by_acc.setdefault(row.get("account_id", ""), []).append(
            _norm_note(row, from_jsonl=from_jsonl)
        )
    for ns in notes_by_acc.values():
        ns.sort(key=lambda n: (_eng(n), n["date"]), reverse=True)

    # 账号集合：有 watchlist → 盯的账号；否则 → 搜索榜单
    tracked = bool(watch)
    if tracked:
        base = [(w["account_id"], w.get("nickname", ""), w.get("source", "")) for w in watch]
    else:
        base = [(r["account_id"], r.get("nickname", ""), "rank") for r in ranks]

    has_profiles = bool(prof)
    accounts = []
    for aid, nickname, source in base:
        c = cre.get(aid)
        p = prof.get(aid)
        rk = rankmap.get(aid)
        nickname = nickname or (c or {}).get("nickname") or (rk or {}).get("nickname") or aid
        accounts.append(
            {
                "account_id": aid,
                "nickname": nickname,
                "source": source,
                "has_profile": c is not None,
                "verify_type": _int(c["verify_type"]) if c else None,
                "red_id": (c or {}).get("red_id", ""),
                "fans": _int(c["fans"]) if c else None,
                "follows": _int(c["follows"]) if c else None,
                "ip_location": (c or {}).get("ip_location", ""),
                "has_pf": p is not None,
                "vertical_ratio": _float(p["vertical_ratio"]) if p else 0.0,
                "recent_note_count": _int(p["recent_note_count"]) if p else 0,
                "profile_score": _float(p["profile_score"]) if p else 0.0,
                "has_rank": rk is not None,
                "account_score": _float(rk["account_score"]) if rk else 0.0,
                "relevant_note_count": _int(rk["relevant_note_count"]) if rk else 0,
                "keyword_hit_count": _int(rk["keyword_hit_count"]) if rk else 0,
                "avg_interaction": _float(rk["avg_interaction"]) if rk else 0.0,
                "notes": notes_by_acc.get(aid, []),
            }
        )

    sort_key = "profile_score" if has_profiles else "account_score"
    accounts.sort(key=lambda a: a[sort_key], reverse=True)
    max_score = max((a["account_score"] for a in accounts), default=0.0) or 1.0

    # 选题流：所有窗内/搜索笔记按互动降序
    feed = []
    nick_by_acc = {a["account_id"]: a["nickname"] for a in accounts}
    for row in note_source:
        n = _norm_note(row, from_jsonl=from_jsonl)
        feed.append(
            {
                **n,
                "nickname": row.get("nickname") or nick_by_acc.get(row.get("account_id", ""), ""),
                "eng": _eng(n),
            }
        )
    feed.sort(key=lambda x: (x["eng"], x["date"]), reverse=True)

    collected_at = ""
    if tf:
        collected_at = tf[0].get("collected_at", "")
    elif notes_csv:
        collected_at = notes_csv[0].get("collected_at", "")

    return {
        "run_dir": run_dir.name,
        "collected_at": collected_at,
        "tracked": tracked,
        "has_profiles": has_profiles,
        "window_feed": from_jsonl,
        "max_score": round(max_score, 2),
        "summary": {
            "accounts": len(accounts),
            "notes": len(feed),
            "profiles": len(cre),
            "verified": sum(1 for a in accounts if a["verify_type"] == 2),
        },
        "accounts": accounts,
        "feed": feed,
    }


def build_report(run_dir) -> Path:
    """读 run_dir 导出 → 写 run_dir/data.js + 拷入静态资源，返回 index.html 路径。"""
    run_dir = Path(run_dir)
    payload = json.dumps(assemble(run_dir), ensure_ascii=False)
    (run_dir / "data.js").write_text(f"window.DATA = {payload};\n", encoding="utf-8")

    web_dir = Path(__file__).parent
    for name in _STATIC_ASSETS:
        shutil.copyfile(web_dir / name, run_dir / name)
    return run_dir / "index.html"
