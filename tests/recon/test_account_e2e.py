import csv
from pathlib import Path

import yaml
from typer.testing import CliRunner

from src.recon.entrypoints.cli import app

runner = CliRunner()


def test_account_cli_reads_config_and_writes_three_outputs(tmp_path, monkeypatch):
    out = tmp_path / "exports"
    config = tmp_path / "run.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "provider": "fixture",
                "fixture_path": "tests/fixtures/search_contents_sample.jsonl",
                "creator_fixture_path": "tests/fixtures/creator_contents_sample.jsonl",
                "creator_profiles_fixture_path": "tests/fixtures/creator_creators_sample.jsonl",
                "account_analysis": {
                    "accounts": ["601d0481000000000101cc46"],
                    "max_notes": None,
                    "fetch_comments": False,
                },
                "logging": {"file_enabled": False},
                "export": {"out_dir": str(out)},
                "store": {"enabled": False},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.recon.entrypoints.runtime.now_iso", lambda: "2026-01-01T00:00:00+00:00"
    )
    result = runner.invoke(app, ["account", "--config", str(config)])
    assert result.exit_code == 0, result.output
    assert "账号分析开始" in result.output
    assert "账号采集完成" in result.output
    assert "账号分析输出完成" in result.output

    latest = (out / "account" / "latest").resolve()
    assert {path.name for path in latest.iterdir()} == {
        "account_summary.csv",
        "account_contents.csv",
        "account_report.md",
    }
    rows = list(csv.DictReader((latest / "account_summary.csv").open(encoding="utf-8")))
    assert rows[0]["account_id"] == "601d0481000000000101cc46"
    assert rows[0]["content_count"] == "2"
    assert not (latest / "account_comments.csv").exists()


def test_run_sh_exposes_account_route():
    script = Path("run.sh").read_text(encoding="utf-8")
    assert "src.recon.entrypoints.cli account" in script
