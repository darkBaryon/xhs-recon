import json
import zipfile

import yaml
from typer.testing import CliRunner

from src.recon.entrypoints.cli import app


def test_research_composes_independent_services_and_writes_four_file_bundle(tmp_path, monkeypatch):
    output = tmp_path / "exports"
    config = tmp_path / "run.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "provider": "fixture",
                "fixture_path": "tests/fixtures/search_contents_sample.jsonl",
                "creator_fixture_path": "tests/fixtures/creator_contents_sample.jsonl",
                "creator_profiles_fixture_path": "tests/fixtures/creator_creators_sample.jsonl",
                "keywords": ["留学辅导"],
                "search": {"pages": 1, "limit": 2, "window_days": 0},
                "watchlist": {
                    "manual": [
                        {
                            "account_id": "601d0481000000000101cc46",
                            "nickname": "竞品",
                            "self": True,
                        }
                    ],
                    "auto_top_n": 0,
                    "max_total": 10,
                },
                "creator": {"notes_per_account": 10, "batch_size": 0},
                "comments": {"enabled": False},
                "logging": {"file_enabled": False},
                "export": {"out_dir": str(output)},
                "store": {"enabled": False},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.recon.entrypoints.runtime.now_iso", lambda: "2026-07-17T00:00:00Z")

    result = CliRunner().invoke(app, ["research", "--config", str(config)])

    assert result.exit_code == 0, result.output
    zip_path = next((output / "research").glob("*.zip"))
    with zipfile.ZipFile(zip_path) as archive:
        prefix = zip_path.stem
        assert set(archive.namelist()) == {
            f"{prefix}/README.md",
            f"{prefix}/research.json",
            f"{prefix}/accounts.json",
            f"{prefix}/notes.jsonl",
        }
        research = json.loads(archive.read(f"{prefix}/research.json"))
        accounts = json.loads(archive.read(f"{prefix}/accounts.json"))
        notes = [
            json.loads(line) for line in archive.read(f"{prefix}/notes.jsonl").decode().splitlines()
        ]
    assert research["watchlist"]["self_count"] == 1
    assert accounts[0]["source"] == "self"
    assert {note["side"] for note in notes} == {"search", "creator"}
