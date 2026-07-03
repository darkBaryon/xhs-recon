"""keywords_file / watchlist_file 资产引用的加载语义（双源冲突报错、缺文件/缺键报错、正常注入）。"""

import csv
from pathlib import Path

import pytest
import yaml

from src.pipelines.run_research import _resolve_config_refs, run_research


def _write_yaml(path: Path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return str(path)


# --- keywords_file ---


def test_keywords_file_injects_keywords_and_synonyms(tmp_path):
    kf = _write_yaml(
        tmp_path / "kw.yaml",
        {"keywords": ["a"], "synonyms": {"a": ["b"]}},
    )
    config = _resolve_config_refs({"keywords_file": kf})
    assert config["keywords"] == ["a"]
    assert config["synonyms"] == {"a": ["b"]}


def test_keywords_file_conflicts_with_inline_keywords(tmp_path):
    kf = _write_yaml(tmp_path / "kw.yaml", {"keywords": ["a"]})
    with pytest.raises(ValueError, match="不可同时提供"):
        _resolve_config_refs({"keywords_file": kf, "keywords": ["x"]})


def test_keywords_file_conflicts_with_inline_synonyms(tmp_path):
    kf = _write_yaml(tmp_path / "kw.yaml", {"keywords": ["a"]})
    with pytest.raises(ValueError, match="不可同时提供"):
        _resolve_config_refs({"keywords_file": kf, "synonyms": {"x": ["y"]}})


def test_keywords_file_missing_file_fails():
    with pytest.raises(ValueError, match="不存在"):
        _resolve_config_refs({"keywords_file": "no/such/file.yaml"})


def test_keywords_file_missing_keywords_key_fails(tmp_path):
    kf = _write_yaml(tmp_path / "kw.yaml", {"synonyms": {}})
    with pytest.raises(ValueError, match="缺少 keywords 键"):
        _resolve_config_refs({"keywords_file": kf})


# --- watchlist_file ---


def test_watchlist_file_injects_manual(tmp_path):
    wf = _write_yaml(tmp_path / "wl.yaml", {"manual": ["id1"]})
    config = _resolve_config_refs({"watchlist_file": wf, "watchlist": {"auto_top_n": 2}})
    assert config["watchlist"]["manual"] == ["id1"]
    assert config["watchlist"]["auto_top_n"] == 2  # 运行参数保留


def test_watchlist_file_creates_watchlist_section_when_absent(tmp_path):
    wf = _write_yaml(tmp_path / "wl.yaml", {"manual": ["id1"]})
    config = _resolve_config_refs({"watchlist_file": wf})
    assert config["watchlist"] == {"manual": ["id1"]}  # 自动创建，默认 auto_top_n/max_total 生效


def test_watchlist_file_conflicts_with_inline_manual(tmp_path):
    wf = _write_yaml(tmp_path / "wl.yaml", {"manual": ["id1"]})
    with pytest.raises(ValueError, match="不可同时提供"):
        _resolve_config_refs({"watchlist_file": wf, "watchlist": {"manual": ["id2"]}})


def test_watchlist_file_missing_manual_key_fails(tmp_path):
    wf = _write_yaml(tmp_path / "wl.yaml", {"auto_top_n": 3})
    with pytest.raises(ValueError, match="缺少 manual 键"):
        _resolve_config_refs({"watchlist_file": wf})


def test_no_refs_config_passes_through_unchanged():
    config = {"keywords": ["a"], "watchlist": {"manual": ["id1"]}}
    assert _resolve_config_refs(dict(config)) == config


# --- 全管线集成：资产引用跑通 fixture 管线 ---


def test_pipeline_with_asset_files(tmp_path):
    kf = _write_yaml(
        tmp_path / "kw.yaml",
        {"keywords": ["留学辅导"], "synonyms": {"留学辅导": ["essay辅导"]}},
    )
    wf = _write_yaml(tmp_path / "wl.yaml", {"manual": ["601d0481000000000101cc46"]})
    cfg_path = _write_yaml(
        tmp_path / "cfg.yaml",
        {
            "provider": "fixture",
            "fixture_path": "tests/fixtures/search_contents_sample.jsonl",
            "creator_fixture_path": "tests/fixtures/creator_contents_sample.jsonl",
            "keywords_file": kf,
            "watchlist_file": wf,
            "watchlist": {"auto_top_n": 0, "max_total": 5},
            "creator": {"notes_per_account": 3},
            "search": {"pages": 1, "limit": 20, "sort": "", "window_days": 0},
            "logging": {"file_enabled": False},
            "export": {"out_dir": str(tmp_path / "exports")},
        },
    )

    paths = run_research(cfg_path)

    rows = list(csv.DictReader(open(paths["watchlist"], encoding="utf-8")))
    assert [r["account_id"] for r in rows] == ["601d0481000000000101cc46"]  # 资产文件 manual 生效
    assert rows[0]["source"] == "manual"
    assert Path(paths["creator_notes"]).exists()


def test_watchlist_file_manual_object_exports_nickname(tmp_path):
    kf = _write_yaml(tmp_path / "kw.yaml", {"keywords": ["留学辅导"]})
    wf = _write_yaml(
        tmp_path / "wl.yaml",
        {
            "manual": [
                {
                    "account_id": "601d0481000000000101cc46",
                    "nickname": "手写昵称",
                }
            ]
        },
    )
    cfg_path = _write_yaml(
        tmp_path / "cfg.yaml",
        {
            "provider": "fixture",
            "fixture_path": "tests/fixtures/search_contents_sample.jsonl",
            "creator_fixture_path": "tests/fixtures/creator_contents_sample.jsonl",
            "keywords_file": kf,
            "watchlist_file": wf,
            "watchlist": {"auto_top_n": 0, "max_total": 5},
            "creator": {"notes_per_account": 3},
            "search": {"pages": 1, "limit": 20, "sort": "", "window_days": 0},
            "logging": {"file_enabled": False},
            "export": {"out_dir": str(tmp_path / "exports")},
        },
    )

    paths = run_research(cfg_path)

    rows = list(csv.DictReader(open(paths["watchlist"], encoding="utf-8")))
    assert rows[0] == {
        "account_id": "601d0481000000000101cc46",
        "nickname": "手写昵称",
        "source": "manual",
    }
