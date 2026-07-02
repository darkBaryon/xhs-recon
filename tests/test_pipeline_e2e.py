import csv
from pathlib import Path

import yaml

from src.pipelines.run_research import run_research


def _cfg(out_dir: Path) -> dict:
    return {
        "provider": "fixture",
        "fixture_path": "tests/fixtures/search_contents_sample.jsonl",
        "keywords": ["留学辅导"],
        "search": {"pages": 1, "limit": 20},
        "ranking": {"weights": {"note_count": 10, "keyword_hit": 5, "interaction": 0.01}},
        "selection": {"top_notes_per_account": 2},
        "export": {"out_dir": str(out_dir)},
    }


def test_pipeline_end_to_end(tmp_path):
    cfg = _cfg(tmp_path)
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    paths = run_research(str(cfg_path))

    for key in ["accounts", "notes", "account_rank", "typical_notes", "report_input"]:
        assert Path(paths[key]).exists()
    assert "comments" not in paths

    with open(tmp_path / "accounts.csv", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) - 1 == 5  # sample 5 个不同作者 → 去重后 5 个账号

    md = (tmp_path / "report_input.md").read_text(encoding="utf-8")
    assert md.strip() != ""


def test_pipeline_end_to_end_with_comments(tmp_path, monkeypatch):
    monkeypatch.setattr("src.pipelines.run_research._now_iso", lambda: "2026")
    cfg = _cfg(tmp_path)
    cfg["comments"] = {
        "enabled": True,
        "limit": 10,
        "report_top_k": 3,
        "fixture_path": "tests/fixtures/comments.jsonl",
    }
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    paths = run_research(str(cfg_path))

    assert set(paths) == {
        "accounts",
        "notes",
        "account_rank",
        "typical_notes",
        "comments",
        "report_input",
    }
    with open(tmp_path / "comments.csv", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["body", "note_id", "like_count", "collected_at"]
    assert rows[1][0].startswith("这个角度")
    assert rows[1][2] == "12000"

    md = (tmp_path / "report_input.md").read_text(encoding="utf-8")
    assert "评论 12000赞：这个角度很有帮助" in md
    exported_text = "\n".join(
        p.read_text(encoding="utf-8") for p in tmp_path.iterdir() if p.is_file()
    )
    assert "user-secret" not in exported_text
    assert "不应落盘" not in exported_text
    assert "avatar.example" not in exported_text


def test_pipeline_comments_disabled_matches_phase2_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr("src.pipelines.run_research._now_iso", lambda: "2026")
    base_dir = tmp_path / "base"
    disabled_dir = tmp_path / "disabled"
    base_cfg = _cfg(base_dir)
    disabled_cfg = _cfg(disabled_dir)
    disabled_cfg["comments"] = {
        "enabled": False,
        "limit": 10,
        "fixture_path": "tests/fixtures/comments.jsonl",
    }

    base_cfg_path = tmp_path / "base.yaml"
    disabled_cfg_path = tmp_path / "disabled.yaml"
    base_cfg_path.write_text(yaml.safe_dump(base_cfg, allow_unicode=True), encoding="utf-8")
    disabled_cfg_path.write_text(yaml.safe_dump(disabled_cfg, allow_unicode=True), encoding="utf-8")

    base_paths = run_research(str(base_cfg_path))
    disabled_paths = run_research(str(disabled_cfg_path))

    assert set(disabled_paths) == {
        "accounts",
        "notes",
        "account_rank",
        "typical_notes",
        "report_input",
    }
    assert not (disabled_dir / "comments.csv").exists()
    for key in disabled_paths:
        assert Path(disabled_paths[key]).read_bytes() == Path(base_paths[key]).read_bytes()
