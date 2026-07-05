from pathlib import Path

import yaml

from src.pipelines.run_research import run_research


def _cfg(out_dir: Path) -> dict:
    return {
        "provider": "fixture",
        "fixture_path": "tests/fixtures/search_contents_sample.jsonl",
        "keywords": ["留学辅导"],
        "search": {"pages": 1, "limit": 20, "sort": "", "window_days": 0},
        "ranking": {"weights": {"note_count": 10, "keyword_hit": 5, "interaction": 0.01}},
        "selection": {"top_notes_per_account": 2, "half_life_days": 0},
        "comments": {"enabled": False},
        "logging": {"file_enabled": False},
        "export": {"out_dir": str(out_dir)},
    }


def test_each_run_gets_own_dir_and_latest_points_newest(tmp_path, monkeypatch):
    run_ids = iter(["2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"])
    monkeypatch.setattr("src.pipelines.runtime.now_iso", lambda: next(run_ids))
    out_base = tmp_path / "exports"
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(_cfg(out_base), allow_unicode=True))

    paths1 = run_research(str(cfg_path))
    paths2 = run_research(str(cfg_path))

    dir1 = out_base / "20260101T000000"
    dir2 = out_base / "20260102T000000"
    # 两次运行各自成目录，历史不被覆盖
    assert (dir1 / "report_input.md").exists()
    assert (dir2 / "report_input.md").exists()
    assert Path(paths1["report_input"]).parent == dir1
    assert Path(paths2["report_input"]).parent == dir2
    # latest 软链指向最新一次，且可经软链读取
    latest = out_base / "latest"
    assert latest.is_symlink()
    assert latest.resolve() == dir2.resolve()
    assert (latest / "report_input.md").read_bytes() == (dir2 / "report_input.md").read_bytes()


def test_latest_not_symlink_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr("src.pipelines.runtime.now_iso", lambda: "2026-01-03T00:00:00+00:00")
    out_base = tmp_path / "exports"
    out_base.mkdir(parents=True)
    (out_base / "latest").mkdir()  # 同名实体目录（异常情形），不得被删改
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(_cfg(out_base), allow_unicode=True))

    run_research(str(cfg_path))

    assert (out_base / "latest").is_dir() and not (out_base / "latest").is_symlink()
    assert (out_base / "20260103T000000" / "report_input.md").exists()  # 导出本身不受影响
