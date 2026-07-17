"""研究快照 bundle：research/accounts/notes + README 打包成 zip，字段口径正确。"""

import csv
import json
import zipfile
from pathlib import Path

from src.recon.entrypoints.config_models import RunConfig
from web.bundle import _in_window, build_bundle


def _csv(path: Path, header: list[str], rows: list[list]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _run_dir(d: Path):
    _csv(
        d / "watchlist.csv",
        ["account_id", "nickname", "source"],
        [["U1", "机构甲", "manual"], ["U2", "老师乙", "auto"]],
    )
    _csv(
        d / "creator_profiles.csv",
        [
            "account_id",
            "nickname",
            "verify_type",
            "red_id",
            "fans",
            "follows",
            "interaction",
            "tags",
            "desc",
            "ip_location",
        ],
        [["U1", "机构甲", "2", "888", "12000", "30", "5000", "", "教育科技", "上海"]],
    )
    _csv(
        d / "account_profile.csv",
        ["account_id", "nickname", "vertical_ratio", "recent_note_count", "profile_score"],
        [["U1", "机构甲", "1.0000", "5", "15.00"]],
    )
    _csv(
        d / "creator_notes.csv",
        [
            "note_id",
            "account_id",
            "title",
            "body",
            "tags",
            "url",
            "like_count",
            "collect_count",
            "comment_count",
            "published_at",
            "collected_at",
            "source_keywords",
            "raw_path",
        ],
        [
            [
                "N1",
                "U1",
                "窗内帖",
                "正文",
                "留学|dissertation",
                "http://x/N1",
                "0",
                "0",
                "0",
                "2026-07-05T00:00:00+00:00",
                "2026-07-06T00:00:00+00:00",
                "",
                "p",
            ],
            [
                "N2",
                "U1",
                "出窗帖",
                "老正文",
                "留学",
                "http://x/N2",
                "0",
                "0",
                "0",
                "2026-01-01T00:00:00+00:00",
                "2026-07-06T00:00:00+00:00",
                "",
                "p",
            ],
        ],
    )


def _config() -> RunConfig:
    return RunConfig.model_validate(
        {
            "provider": "mediacrawler",
            "keywords": ["留学生辅导", "论文辅导"],
            "synonyms": {"留学生辅导": ["课业辅导"]},
            "search": {"window_days": 30},
            "watchlist": {"manual": ["U1", "U2"], "auto_top_n": 2, "max_total": 10},
            "creator": {"notes_per_account": 10},
        }
    )


def test_in_window():
    assert _in_window("2026-07-05T00:00:00+00:00", "2026-07-06T00:00:00+00:00", 30) is True
    assert _in_window("2026-01-01T00:00:00+00:00", "2026-07-06T00:00:00+00:00", 30) is False
    assert _in_window("", "2026-07-06T00:00:00+00:00", 30) is None  # 缺发布时间
    assert _in_window("2026-01-01T00:00:00+00:00", "x", 0) is True  # 不开窗全算窗内


def test_build_bundle_zip(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _run_dir(run_dir)
    out = tmp_path / "out"

    zip_path = build_bundle(run_dir, _config(), out_dir=out)
    assert zip_path.suffix == ".zip"

    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        stem = zip_path.stem  # 主题-时间戳
        assert set(names) == {
            f"{stem}/README.md",
            f"{stem}/research.json",
            f"{stem}/accounts.json",
            f"{stem}/notes.jsonl",
        }

        research = json.loads(z.read(f"{stem}/research.json"))
        # 输入侧落地：种子词 + 扩展 + 窗口 + watchlist 配置
        assert research["seed_keywords"] == ["留学生辅导", "论文辅导"]
        assert "课业辅导" in research["expanded_keywords"]
        assert research["window_days"] == 30
        assert research["watchlist"] == {
            "manual_count": 2,
            "self_count": 0,
            "auto_top_n": 2,
            "max_total": 10,
        }

        accounts = json.loads(z.read(f"{stem}/accounts.json"))
        u1 = next(a for a in accounts if a["account_id"] == "U1")
        assert u1["verify_type"] == 2 and u1["fans"] == 12000  # 档案 fans 已归一化整数
        assert u1["profile_score"] == 15.0

        notes = [json.loads(x) for x in z.read(f"{stem}/notes.jsonl").decode().splitlines()]
        by_id = {n["note_id"]: n for n in notes}
        assert by_id["N1"]["in_window"] is True  # 近期帖
        assert by_id["N2"]["in_window"] is False  # 老帖出窗
        assert by_id["N1"]["side"] == "creator"
        assert by_id["N1"]["tags"] == ["留学", "dissertation"]

        readme = z.read(f"{stem}/README.md").decode()
        assert "verify_type" in readme and "未采集" in readme  # 自描述含关键口径


def test_build_bundle_search_only(tmp_path):
    # 无 watchlist：账号取自 account_rank，笔记取自 notes.csv
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _csv(
        run_dir / "account_rank.csv",
        [
            "account_id",
            "nickname",
            "relevant_note_count",
            "keyword_hit_count",
            "avg_interaction",
            "account_score",
            "note_ids",
        ],
        [["A1", "账号一", "3", "1", "200.0", "45.5", "N1|N2"]],
    )
    _csv(
        run_dir / "notes.csv",
        [
            "note_id",
            "account_id",
            "title",
            "body",
            "tags",
            "url",
            "like_count",
            "collect_count",
            "comment_count",
            "published_at",
            "collected_at",
            "source_keywords",
            "raw_path",
        ],
        [
            [
                "N1",
                "A1",
                "热帖",
                "",
                "留学",
                "http://x/N1",
                "300",
                "20",
                "5",
                "2026-07-02T00:00:00+00:00",
                "2026-07-03T00:00:00+00:00",
                "留学辅导",
                "p",
            ]
        ],
    )

    cfg = RunConfig.model_validate({"keywords": ["留学"], "search": {"window_days": 0}})
    zip_path = build_bundle(run_dir, cfg, out_dir=tmp_path / "out")
    with zipfile.ZipFile(zip_path) as z:
        stem = zip_path.stem
        accounts = json.loads(z.read(f"{stem}/accounts.json"))
        assert accounts[0]["account_id"] == "A1" and accounts[0]["account_score"] == 45.5
        notes = [json.loads(x) for x in z.read(f"{stem}/notes.jsonl").decode().splitlines()]
        assert notes[0]["side"] == "search" and notes[0]["like_count"] == 300  # 搜索侧有真实互动
