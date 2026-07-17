from typer.testing import CliRunner

from src.recon.entrypoints import cli


def test_new_web_entry_reads_candidate_schema_explicitly(tmp_path, monkeypatch):
    config = tmp_path / "run.yaml"
    config.write_text("store:\n  database: candidate\n", encoding="utf-8")
    calls = []

    def build(out, database, keyword):
        calls.append((out, database, keyword))
        return out / "index.html"

    import web.feed

    monkeypatch.setattr(web.feed, "build_recon_feed", build)
    out = tmp_path / "site"
    result = CliRunner().invoke(
        cli.app,
        [
            "web",
            "--config",
            str(config),
            "--keyword",
            "留学辅导",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [(out, "candidate", "留学辅导")]


def test_bundle_entry_returns_latest_new_research_bundle(tmp_path):
    export = tmp_path / "exports"
    root = export / "research"
    root.mkdir(parents=True)
    older = root / "topic-20260101.zip"
    latest = root / "topic-20260717.zip"
    older.write_bytes(b"old")
    latest.write_bytes(b"new")
    config = tmp_path / "run.yaml"
    config.write_text(f"export:\n  out_dir: {export}\n", encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["bundle", "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert f"bundle: {latest}" in result.output
