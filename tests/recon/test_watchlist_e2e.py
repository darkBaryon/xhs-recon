import csv
from types import SimpleNamespace

import yaml
from typer.testing import CliRunner

from src.recon.entrypoints import cli


def test_watchlist_cli_reads_only_manual_yaml_accounts(tmp_path, monkeypatch):
    output = tmp_path / "exports"
    config = tmp_path / "run.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "provider": "fixture",
                "fixture_path": "tests/fixtures/search_contents_sample.jsonl",
                "creator_fixture_path": "tests/fixtures/creator_contents_sample.jsonl",
                "creator_profiles_fixture_path": "tests/fixtures/creator_creators_sample.jsonl",
                "watchlist": {
                    "manual": ["601d0481000000000101cc46"],
                    "auto_top_n": 99,
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
    monkeypatch.setattr("src.recon.entrypoints.runtime.now_iso", lambda: "2026-07-16T00:00:00Z")

    result = CliRunner().invoke(cli.app, ["watchlist", "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert "Watchlist 开始：到期 1/1" in result.output
    latest = (output / "watchlist" / "latest").resolve()
    rows = list(csv.DictReader((latest / "watchlist_contents.csv").open(encoding="utf-8")))
    assert len(rows) == 2
    assert {row["account_id"] for row in rows} == {"601d0481000000000101cc46"}


def test_watchlist_loop_runs_batches_until_final_short_batch(monkeypatch):
    loaded = SimpleNamespace(
        targets=(object(), object()),
        run=SimpleNamespace(
            creator=SimpleNamespace(notes_per_account=6, batch_size=2, refresh_days=3),
            comments=SimpleNamespace(enabled=True, refresh_days=0),
            store=SimpleNamespace(enabled=True),
        ),
    )
    due_batches = [("a", "b"), ("c",)]
    repositories = []
    sleeps = []

    class Repository:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class UseCase:
        def execute(self, request):
            return SimpleNamespace(
                analysis=SimpleNamespace(due=due_batches.pop(0)),
                output_paths={"report": "watchlist.md"},
            )

    def build(*args, **kwargs):
        repository = Repository()
        repositories.append(repository)
        return UseCase(), repository

    monkeypatch.setattr(cli, "load_watchlist_config", lambda path: loaded)
    monkeypatch.setattr(cli, "build_watchlist_use_case", build)
    monkeypatch.setattr(cli.runtime, "now_iso", lambda: "2026-07-17T00:00:00Z")
    monkeypatch.setattr(cli.random, "randint", lambda low, high: 0)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = CliRunner().invoke(
        cli.app,
        [
            "watchlist",
            "--config",
            "run.yaml",
            "--loop",
            "--pause-min",
            "0",
            "--pause-max",
            "0",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(repositories) == 2
    assert all(repository.closed for repository in repositories)
    assert sleeps == [0]


def test_run_sh_routes_all_replaced_daily_commands_to_recon():
    script = open("run.sh", encoding="utf-8").read()

    assert "src.recon.entrypoints.cli research --config configs/sample.yaml" in script
    assert 'src.recon.entrypoints.cli watchlist --config "$CONFIG" --loop' in script
    assert 'src.pipelines.cli "$cmd"' not in script
