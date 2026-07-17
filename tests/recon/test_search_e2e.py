import csv

import yaml
from typer.testing import CliRunner

from src.recon.entrypoints.cli import app


def test_search_cli_uses_yaml_and_keeps_keyword_ownership(tmp_path, monkeypatch):
    output = tmp_path / "exports"
    logs = tmp_path / "logs"
    config = tmp_path / "run.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "provider": "fixture",
                "fixture_path": "tests/fixtures/search_contents_sample.jsonl",
                "keywords": ["留学辅导"],
                "synonyms": {"留学辅导": ["essay辅导"]},
                "search": {"pages": 1, "limit": 2, "sort": "time_descending"},
                "logging": {"file_enabled": True, "dir": str(logs)},
                "export": {"out_dir": str(output)},
                "store": {"enabled": False},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.recon.entrypoints.runtime.now_iso", lambda: "2026-07-16T00:00:00Z")

    result = CliRunner().invoke(app, ["search", "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert "关键词搜索开始" in result.output
    assert "关键词「留学辅导」完成" in result.output
    assert "搜索汇总完成" in result.output
    latest = (output / "search" / "latest").resolve()
    rows = list(csv.DictReader((latest / "search_contents.csv").open(encoding="utf-8")))
    assert len(rows) == 2
    assert rows[0]["keywords"] == "留学辅导|essay辅导"
    assert {path.name for path in latest.iterdir()} == {
        "search_contents.csv",
        "search_accounts.csv",
        "search_report.md",
    }
    report = (latest / "search_report.md").read_text(encoding="utf-8")
    assert "## 摘要" in report
    assert "- 配置关键词：2" in report
    assert "## 关键词覆盖" in report
    assert "| 留学辅导 | 2 | 2 | 完成 |" in report
    log_text = next(logs.glob("run-*.log")).read_text(encoding="utf-8")
    assert "关键词搜索开始" in log_text
    assert "归属已保存" in log_text
    assert "搜索分析输出完成" in log_text
