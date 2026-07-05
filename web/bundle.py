"""把一次运行目录的导出 + 研究输入，打包成自描述的研究文件夹并 zip。

面向下游程序 / LLM（非人读——人走 cli web）。一个 zip 解压即得完整快照：
- README.md      自描述：这是什么、字段口径、坑（互动=0=未采集、verify_type 码表、窗口语义）
- research.json  输入侧：种子词/同义词/实搜全词/窗口/watchlist 配置/数据源/采集时间
- accounts.json  账号侧：每账号 认证+档案+打分+note_ids
- notes.jsonl    内容侧：全部笔记（creator + search），完整字段 + in_window 标记

数据来自 run_dir 的导出 CSV（web.report 的读取 helper 复用）；研究输入来自 RunConfig。
"""

import json
import zipfile
from datetime import datetime
from pathlib import Path

from src.core.keyword_expander import expand_keywords
from web.report import _int, _read_csv

PIPE = "|"


def _parse_iso(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _in_window(published_at: str, collected_at, window_days: int) -> bool | None:
    """窗内判定：window_days<=0 全算窗内；缺 published_at → None（未知）。"""
    if window_days <= 0:
        return True
    pub, now = _parse_iso(published_at), _parse_iso(collected_at)
    if pub is None or now is None:
        return None
    return (now - pub).total_seconds() / 86400 <= window_days


def _split_tags(raw) -> list[str]:
    return [t for t in str(raw or "").split(PIPE) if t]


def _research(config, collected_at: str) -> dict:
    """研究输入侧：把 RunConfig 的定义落成一等公民（现在任何导出都缺这块）。"""
    seed = list(config.keywords or [])
    synonyms = config.synonyms or {}
    wl = config.watchlist
    return {
        "collected_at": collected_at,
        "provider": config.provider,
        "seed_keywords": seed,
        "synonyms": synonyms,
        "expanded_keywords": expand_keywords(seed, synonyms),
        "window_days": config.search.window_days,
        "notes_per_account": config.creator.notes_per_account,
        "watchlist": None
        if wl is None
        else {
            "manual_count": len(wl.manual),
            "self_count": sum(
                1 for e in wl.manual if isinstance(e, dict) and (e.get("self") or e.get("owner"))
            ),
            "auto_top_n": wl.auto_top_n,
            "max_total": wl.max_total,
        },
    }


def _accounts(run_dir: Path) -> list[dict]:
    watch = _read_csv(run_dir / "watchlist.csv")
    cre = {r["account_id"]: r for r in _read_csv(run_dir / "creator_profiles.csv")}
    prof = {r["account_id"]: r for r in _read_csv(run_dir / "account_profile.csv")}
    ranks = _read_csv(run_dir / "account_rank.csv")
    rankmap = {r["account_id"]: r for r in ranks}

    # 账号集合：有 watchlist → 盯的账号；否则 → 搜索榜单
    base = (
        [(w["account_id"], w.get("nickname", ""), w.get("source", "")) for w in watch]
        if watch
        else [(r["account_id"], r.get("nickname", ""), "rank") for r in ranks]
    )

    out = []
    for aid, nickname, source in base:
        c, p, rk = cre.get(aid), prof.get(aid), rankmap.get(aid)
        nickname = nickname or (c or {}).get("nickname") or (rk or {}).get("nickname") or aid
        out.append(
            {
                "account_id": aid,
                "nickname": nickname,
                "source": source,
                "verify_type": _int(c["verify_type"]) if c else None,
                "red_id": (c or {}).get("red_id", ""),
                "fans": _int(c["fans"]) if c else None,
                "follows": _int(c["follows"]) if c else None,
                "ip_location": (c or {}).get("ip_location", ""),
                "desc": (c or {}).get("desc", ""),
                "account_score": float(rk["account_score"]) if rk else None,
                "relevant_note_count": _int(rk["relevant_note_count"]) if rk else None,
                "keyword_hit_count": _int(rk["keyword_hit_count"]) if rk else None,
                "profile_score": float(p["profile_score"]) if p else None,
                "vertical_ratio": float(p["vertical_ratio"]) if p else None,
                "recent_note_count": _int(p["recent_note_count"]) if p else None,
                "note_ids": _split_tags(rk["note_ids"]) if rk else [],
            }
        )
    return out


def _notes(run_dir: Path, window_days: int) -> list[dict]:
    """creator + search 两侧笔记合并；creator 侧标 in_window，互动 0 是未采集非真实。"""
    rows = []
    for fname, side in (("creator_notes.csv", "creator"), ("notes.csv", "search")):
        for r in _read_csv(run_dir / fname):
            pub = r.get("published_at", "")
            rows.append(
                {
                    "account_id": r.get("account_id", ""),
                    "nickname": r.get("nickname", ""),
                    "side": side,
                    "note_id": r.get("note_id", ""),
                    "title": r.get("title", ""),
                    "body": r.get("body", ""),
                    "tags": _split_tags(r.get("tags")),
                    "url": r.get("url", ""),
                    "published_at": pub,
                    "in_window": _in_window(pub, r.get("collected_at"), window_days),
                    "like_count": _int(r.get("like_count")),
                    "collect_count": _int(r.get("collect_count")),
                    "comment_count": _int(r.get("comment_count")),
                }
            )
    return rows


_README = (Path(__file__).parent / "bundle_readme.md").read_text(encoding="utf-8")


def build_bundle(run_dir, config, out_dir=None):
    """读 run_dir 导出 + config 输入 → 写研究文件夹 → zip，返回 zip 路径。"""
    run_dir = Path(run_dir)
    notes_csv = _read_csv(run_dir / "creator_notes.csv") or _read_csv(run_dir / "notes.csv")
    collected_at = notes_csv[0].get("collected_at", "") if notes_csv else ""
    window_days = config.search.window_days

    seed = config.keywords or ["research"]
    topic = str(seed[0])
    stamp = "".join(ch for ch in collected_at.split(".")[0] if ch.isalnum() or ch == "T") or "run"
    name = f"{topic}-{stamp}"

    base = Path(out_dir) if out_dir else run_dir.parent
    folder = base / name
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "research.json").write_text(
        json.dumps(_research(config, collected_at), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (folder / "accounts.json").write_text(
        json.dumps(_accounts(run_dir), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with open(folder / "notes.jsonl", "w", encoding="utf-8") as f:
        for n in _notes(run_dir, window_days):
            f.write(json.dumps(n, ensure_ascii=False) + "\n")
    (folder / "README.md").write_text(_README.format(topic=topic), encoding="utf-8")

    zip_path = base / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for item in sorted(folder.iterdir()):
            z.write(item, f"{name}/{item.name}")
    return zip_path
