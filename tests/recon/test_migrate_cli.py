from typer.testing import CliRunner

from src.recon.entrypoints import cli
from src.recon.infrastructure.persistence.mysql.legacy_import import LegacyImportReport


class Repository:
    connection = object()

    def __init__(self, database):
        self.database = database

    def close(self):
        return None


class Importer:
    dry_run = None

    def __init__(self, connection):
        pass

    def run(self, *, dry_run):
        type(self).dry_run = dry_run
        return LegacyImportReport(1, 2, 3, 4, 5, dry_run)


class Connection:
    closed = False

    def close(self):
        type(self).closed = True


def test_migrate_cli_defaults_to_dry_run(tmp_path, monkeypatch):
    config = tmp_path / "run.yaml"
    config.write_text("store:\n  database: candidate\n", encoding="utf-8")
    connection = Connection()
    monkeypatch.setattr(cli, "connect_existing_database", lambda database: connection)
    monkeypatch.setattr(
        cli,
        "MySQLResearchRepository",
        lambda database: (_ for _ in ()).throw(AssertionError("dry-run initialized schema")),
    )
    monkeypatch.setattr(cli, "LegacyImporter", Importer)

    result = CliRunner().invoke(cli.app, ["migrate-legacy", "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert Importer.dry_run is True
    assert Connection.closed is True
    assert "DRY-RUN: creators=1 contents=2 comments=3 keywords=4 media=5" in result.output


def test_migrate_cli_requires_explicit_apply(tmp_path, monkeypatch):
    config = tmp_path / "run.yaml"
    config.write_text("store:\n  database: candidate\n", encoding="utf-8")
    monkeypatch.setattr(cli, "MySQLResearchRepository", Repository)
    monkeypatch.setattr(cli, "LegacyImporter", Importer)

    result = CliRunner().invoke(cli.app, ["migrate-legacy", "--config", str(config), "--apply"])

    assert result.exit_code == 0, result.output
    assert Importer.dry_run is False
