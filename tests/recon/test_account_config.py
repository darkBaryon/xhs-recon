from pathlib import Path

import pytest
import yaml

from src.recon.entrypoints.config import load_account_config, resolve_config_refs
from src.recon.entrypoints.container import build_account_use_case


def _yaml(path: Path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return str(path)


def test_account_file_injects_long_lived_targets(tmp_path):
    account_id = "601d0481000000000101cc46"
    accounts = _yaml(tmp_path / "accounts.yaml", {"accounts": [{"id": account_id, "name": "A"}]})
    cfg = _yaml(
        tmp_path / "run.yaml",
        {
            "provider": "fixture",
            "account_analysis_file": accounts,
            "account_analysis": {"max_notes": 3},
        },
    )
    loaded = load_account_config(cfg)
    assert loaded.targets[0].id.external_id == account_id
    assert loaded.targets[0].nickname == "A"
    assert loaded.run.account_analysis.max_notes == 3


def test_account_file_and_inline_targets_conflict(tmp_path):
    accounts = _yaml(tmp_path / "accounts.yaml", {"accounts": ["abc"]})
    with pytest.raises(ValueError, match="不可同时提供"):
        resolve_config_refs(
            {
                "account_analysis_file": accounts,
                "account_analysis": {"accounts": ["def"]},
            }
        )


def test_account_config_requires_targets(tmp_path):
    cfg = _yaml(tmp_path / "run.yaml", {"provider": "fixture"})
    with pytest.raises(ValueError, match="account_analysis"):
        load_account_config(cfg)


def test_incremental_is_not_silently_ignored(tmp_path):
    cfg = _yaml(
        tmp_path / "run.yaml",
        {
            "provider": "fixture",
            "account_analysis": {"accounts": ["abc"], "incremental": True},
        },
    )
    with pytest.raises(ValueError, match="尚未实现"):
        load_account_config(cfg)


def test_account_live_mode_does_not_fall_back_to_fixture(tmp_path):
    missing = tmp_path / "missing-mediacrawler"
    cfg = _yaml(
        tmp_path / "run.yaml",
        {
            "provider": "mediacrawler",
            "mediacrawler_dir": str(missing),
            "account_analysis": {"accounts": ["601d0481000000000101cc46"]},
        },
    )
    loaded = load_account_config(cfg)

    with pytest.raises(ValueError, match="MediaCrawler 目录不可用"):
        build_account_use_case(loaded, "2026", verbose=False)
