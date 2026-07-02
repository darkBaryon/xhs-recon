import logging
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
        "comments": {
            "enabled": True,
            "limit": 10,
            "fixture_path": "tests/fixtures/comments.jsonl",
        },
        "logging": {"file_enabled": False},
        "export": {"out_dir": str(out_dir)},
    }


def test_run_research_logs_stage_lines_and_keyword(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("src.pipelines.run_research._now_iso", lambda: "2026")
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(_cfg(tmp_path / "out"), allow_unicode=True))

    with caplog.at_level(logging.INFO):
        run_research(str(cfg_path), verbose=True)

    text = caplog.text
    assert "keywords expanded:" in text
    assert "search kw=留学辅导 p1:" in text
    assert "aggregate:" in text
    assert "rank:" in text
    assert "select typical:" in text
    assert "comments:" in text
    assert "export:" in text
    assert any(r.levelno == logging.INFO and "kw=" in r.message for r in caplog.records)


def test_run_research_logs_search_error_as_warning(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("src.pipelines.run_research._now_iso", lambda: "2026")
    cfg = _cfg(tmp_path / "out")
    cfg["fixture_path"] = "tests/fixtures/missing.jsonl"
    cfg["comments"] = {"enabled": False}
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True))

    with caplog.at_level(logging.INFO):
        run_research(str(cfg_path))

    assert any(
        r.levelno == logging.WARNING and "search failed:" in r.message for r in caplog.records
    )
