"""report_html 生成器：对 sync 侧 / 搜索侧 / 缺文件三种运行目录都稳健。"""

import csv
import json
from pathlib import Path

from web.report import assemble, build_report


def _csv(path: Path, header: list[str], rows: list[list]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _full_run_dir(d: Path):
    _csv(d / "watchlist.csv", ["account_id", "nickname", "source"],
         [["U1", "机构甲", "manual"], ["U2", "老师乙", "manual"]])
    _csv(d / "creator_profiles.csv",
         ["account_id", "nickname", "verify_type", "red_id", "fans", "follows",
          "interaction", "tags", "desc", "ip_location"],
         [["U1", "机构甲", "2", "888", "12000", "30", "5000", "", "教育科技", "上海"]])
    _csv(d / "account_profile.csv",
         ["account_id", "nickname", "vertical_ratio", "recent_note_count", "profile_score"],
         [["U1", "机构甲", "1.0000", "5", "15.00"], ["U2", "老师乙", "0.5000", "3", "8.00"]])
    _csv(d / "account_rank.csv",
         ["account_id", "nickname", "relevant_note_count", "keyword_hit_count",
          "avg_interaction", "account_score", "note_ids"],
         [["U1", "机构甲", "5", "2", "3000.0", "80.0", "N1|N2"]])
    _csv(d / "creator_notes.csv",
         ["note_id", "account_id", "title", "body", "tags", "url", "like_count",
          "collect_count", "comment_count", "published_at", "collected_at",
          "source_keywords", "raw_path"],
         [["N1", "U1", "低赞帖", "", "留学", "http://x/N1", "10", "0", "0",
           "2026-07-01T00:00:00+00:00", "2026-07-05T19:30:00+00:00", "", "p"],
          ["N2", "U1", "高赞帖", "", "dissertation", "http://x/N2", "500", "100", "0",
           "2026-07-03T00:00:00+00:00", "2026-07-05T19:30:00+00:00", "", "p"]])


def test_assemble_full_snapshot(tmp_path):
    _full_run_dir(tmp_path)
    data = assemble(tmp_path)

    assert data["tracked"] is True
    assert data["creator_side"] is True
    assert data["summary"] == {"accounts": 2, "notes": 2, "profiles": 1, "verified": 1}
    # 按专业度降序：机构甲(15) 在 老师乙(8) 前
    assert [a["nickname"] for a in data["accounts"]] == ["机构甲", "老师乙"]
    u1 = data["accounts"][0]
    assert u1["verify_type"] == 2 and u1["fans"] == 12000
    # 账号内笔记按互动降序：高赞帖在前
    assert [n["title"] for n in u1["notes"]] == ["高赞帖", "低赞帖"]
    # 选题流按互动降序
    assert [p["title"] for p in data["feed"]] == ["高赞帖", "低赞帖"]
    # 无档案账号标记
    assert data["accounts"][1]["has_profile"] is False


def test_assemble_search_only(tmp_path):
    # 只有搜索侧文件：无 watchlist → 走榜单模式，feed 退回 notes.csv
    _csv(tmp_path / "account_rank.csv",
         ["account_id", "nickname", "relevant_note_count", "keyword_hit_count",
          "avg_interaction", "account_score", "note_ids"],
         [["A1", "账号一", "3", "1", "200.0", "45.5", "N1"],
          ["A2", "账号二", "1", "1", "50.0", "20.0", "N2"]])
    _csv(tmp_path / "notes.csv",
         ["note_id", "account_id", "title", "body", "tags", "url", "like_count",
          "collect_count", "comment_count", "published_at", "collected_at",
          "source_keywords", "raw_path"],
         [["N1", "A1", "热帖", "", "留学|辅导", "http://x/N1", "300", "20", "5",
           "2026-07-02T00:00:00+00:00", "2026-07-03T00:00:00+00:00", "留学辅导", "p"]])

    data = assemble(tmp_path)
    assert data["tracked"] is False
    assert data["creator_side"] is False
    assert data["has_profiles"] is False
    # 按 account_score 降序
    assert [a["nickname"] for a in data["accounts"]] == ["账号一", "账号二"]
    a1 = data["accounts"][0]
    assert a1["has_rank"] is True and a1["account_score"] == 45.5
    # tags 从 | 串拆开
    assert data["feed"][0]["tags"] == ["留学", "辅导"]


def test_build_report_writes_selfcontained_site(tmp_path):
    _full_run_dir(tmp_path)
    out = build_report(tmp_path)

    # 运行目录里落齐四件套：index.html + style.css + app.js + data.js
    assert out == tmp_path / "index.html"
    for name in ("index.html", "style.css", "app.js", "data.js"):
        assert (tmp_path / name).exists(), f"缺 {name}"

    # index.html 是手写骨架、引用外部资源，自己不含数据
    html = out.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert 'src="data.js"' in html and 'src="app.js"' in html
    assert "机构甲" not in html  # 数据不在 HTML 里

    # data.js 是 window.DATA = <合法 JSON>;
    data_js = (tmp_path / "data.js").read_text(encoding="utf-8")
    assert data_js.startswith("window.DATA = ")
    payload = data_js[len("window.DATA = ") : data_js.rstrip().rindex(";")]
    parsed = json.loads(payload)
    assert parsed["summary"]["verified"] == 1
    assert "机构甲" in data_js


def test_empty_run_dir_does_not_crash(tmp_path):
    data = assemble(tmp_path)
    assert data["summary"]["accounts"] == 0
    out = build_report(tmp_path)  # 不抛
    assert out.exists()
