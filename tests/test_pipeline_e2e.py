import csv
import re
from pathlib import Path

import pytest
import typer
import yaml

from src.adapters.fixture_adapter import FixtureAdapter
from src.core.ports import ResearchAdapter
from src.models import Account, FetchResult, Note
from src.pipelines.run_research import run_research


def _cfg(out_dir: Path) -> dict:
    return {
        "provider": "fixture",
        "fixture_path": "tests/fixtures/search_contents_sample.jsonl",
        "keywords": ["留学辅导"],
        "search": {"pages": 1, "limit": 20, "sort": "", "window_days": 0},
        "ranking": {"weights": {"note_count": 10, "keyword_hit": 5, "interaction": 0.01}},
        "selection": {"top_notes_per_account": 2, "half_life_days": 0},
        "logging": {"file_enabled": False},  # 测试不往真实 data/logs/ 攒文件（代码评审建议1）
        "export": {"out_dir": str(out_dir)},
    }


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _typical_note_ids(path: Path) -> set[str]:
    return {row["note_id"] for row in _csv_rows(path)}


def _report_note_ids(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"xiaohongshu\.com/explore/([^?\\)]+)", text))


class _NoCreatorCallAdapter(FixtureAdapter):
    def fetch_creator_notes(self, account_ids, limit, collected_at):
        raise AssertionError("fetch_creator_notes should not be called")


class _PartialCreatorAdapter(ResearchAdapter):
    provider_name = "partial-fixture"

    def __init__(self):
        self._fixture = FixtureAdapter("tests/fixtures/search_contents_sample.jsonl")

    def search(self, keyword, page, limit, collected_at):
        return self._fixture.search(keyword, page, limit, collected_at)

    def fetch_creator_notes(self, account_ids, limit, collected_at):
        note = Note(
            note_id="creator-ok-1",
            account_id=account_ids[0],
            title="成功账号主页笔记",
            body="body",
            tags=[],
            url="https://example.com/creator-ok-1",
            like_count=0,
            collect_count=0,
            comment_count=0,
            published_at="2026",
            collected_at=collected_at,
            source_keywords=[],
            raw_path="raw/creator",
        )
        account = Account(
            account_id=account_ids[0],
            nickname="成功昵称",
            source_keywords=[],
            note_count=1,
            first_seen_at=collected_at,
            last_seen_at=collected_at,
        )
        return FetchResult(
            provider=self.provider_name,
            operation="creator_notes",
            collected_at=collected_at,
            notes=[note],
            accounts=[account],
            raw_path="raw/creator",
            error="creator fetch failed: failed-id",
        )


def test_pipeline_end_to_end(tmp_path):
    cfg = _cfg(tmp_path)
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    paths = run_research(str(cfg_path))

    for key in ["accounts", "notes", "account_rank", "typical_notes", "report_input"]:
        assert Path(paths[key]).exists()
    assert "comments" not in paths

    with open(paths["accounts"], encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) - 1 == 5  # sample 5 个不同作者 → 去重后 5 个账号

    md = Path(paths["report_input"]).read_text(encoding="utf-8")
    assert md.strip() != ""
    # 按运行归档：导出落在 out_dir 下的时间戳子目录
    assert Path(paths["report_input"]).parent.parent == tmp_path


def test_pipeline_without_watchlist_does_not_call_fetch_creator_notes(tmp_path, monkeypatch):
    monkeypatch.setattr("src.pipelines.run_research._now_iso", lambda: "2026")
    monkeypatch.setattr(
        "src.pipelines.run_research._build_adapter",
        lambda config: _NoCreatorCallAdapter("tests/fixtures/search_contents_sample.jsonl"),
    )
    cfg = _cfg(tmp_path)
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    paths = run_research(str(cfg_path))

    assert "watchlist" not in paths
    assert "creator_notes" not in paths


def test_pipeline_watchlist_fixture_exports_creator_files_and_keeps_old_outputs(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("src.pipelines.run_research._now_iso", lambda: "2026")
    base_cfg = _cfg(tmp_path / "base")
    watch_cfg = _cfg(tmp_path / "watch")
    watch_cfg["creator_fixture_path"] = "tests/fixtures/creator_contents_sample.jsonl"
    watch_cfg["watchlist"] = {
        "auto_top_n": 2,
        "manual": [
            "https://www.xiaohongshu.com/user/profile/601d0481000000000101cc46?xsec_token=demo"
        ],
        "max_total": 5,
    }
    watch_cfg["creator"] = {"notes_per_account": 3}

    base_cfg_path = tmp_path / "base.yaml"
    watch_cfg_path = tmp_path / "watch.yaml"
    base_cfg_path.write_text(yaml.safe_dump(base_cfg, allow_unicode=True), encoding="utf-8")
    watch_cfg_path.write_text(yaml.safe_dump(watch_cfg, allow_unicode=True), encoding="utf-8")

    base_paths = run_research(str(base_cfg_path))
    watch_paths = run_research(str(watch_cfg_path))

    assert set(watch_paths) == {
        "accounts",
        "notes",
        "account_rank",
        "typical_notes",
        "report_input",
        "watchlist",
        "creator_notes",
    }
    for key in ["accounts", "notes", "account_rank", "typical_notes", "report_input"]:
        assert Path(watch_paths[key]).read_bytes() == Path(base_paths[key]).read_bytes()

    watch_rows = _csv_rows(Path(watch_paths["watchlist"]))
    assert watch_rows[0] == {
        "account_id": "601d0481000000000101cc46",
        "nickname": "陈皮糖",
        "source": "manual",
    }
    assert [row["source"] for row in watch_rows] == ["manual", "auto", "auto"]

    creator_rows = _csv_rows(Path(watch_paths["creator_notes"]))
    assert [row["note_id"] for row in creator_rows] == [
        "6a4661cd0000000017029d86",
        "6a4661a0000000001702c88e",
    ]
    assert all(row["source_keywords"] == "" for row in creator_rows)


def test_pipeline_invalid_manual_ref_fails_fast(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("src.pipelines.run_research._now_iso", lambda: "2026")
    cfg = _cfg(tmp_path)
    cfg["watchlist"] = {
        "auto_top_n": 0,
        "manual": ["https://example.com/user/profile/601d0481000000000101cc46"],
        "max_total": 5,
    }
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    with pytest.raises(typer.Exit) as e:
        run_research(str(cfg_path))

    assert e.value.exit_code == 1
    assert "https://example.com/user/profile/601d0481000000000101cc46" in capsys.readouterr().err


def test_pipeline_adapter_without_creator_support_exports_empty_creator_header(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr("src.pipelines.run_research._now_iso", lambda: "2026")
    cfg = _cfg(tmp_path)
    cfg["watchlist"] = {
        "auto_top_n": 0,
        "manual": ["601d0481000000000101cc46"],
        "max_total": 5,
    }
    cfg["creator"] = {"notes_per_account": 3}
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    paths = run_research(str(cfg_path))

    with open(paths["creator_notes"], encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 1
    assert rows[0][0:3] == ["note_id", "account_id", "title"]
    assert _csv_rows(Path(paths["watchlist"])) == [
        {"account_id": "601d0481000000000101cc46", "nickname": "", "source": "manual"}
    ]


def test_pipeline_partial_creator_failure_still_exports_success_notes(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr("src.pipelines.run_research._now_iso", lambda: "2026")
    monkeypatch.setattr(
        "src.pipelines.run_research._build_adapter",
        lambda config: _PartialCreatorAdapter(),
    )
    cfg = _cfg(tmp_path)
    cfg["watchlist"] = {
        "auto_top_n": 0,
        "manual": ["601d0481000000000101cc46"],
        "max_total": 5,
    }
    cfg["creator"] = {"notes_per_account": 3}
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    with caplog.at_level("WARNING"):
        paths = run_research(str(cfg_path))

    creator_rows = _csv_rows(Path(paths["creator_notes"]))
    assert [row["note_id"] for row in creator_rows] == ["creator-ok-1"]
    assert _csv_rows(Path(paths["watchlist"])) == [
        {
            "account_id": "601d0481000000000101cc46",
            "nickname": "成功昵称",
            "source": "manual",
        }
    ]
    assert "creator fetch failed: failed-id" in caplog.text


def test_pipeline_window_filters_before_aggregate(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("src.pipelines.run_research._now_iso", lambda: "2026-07-02T00:00:00+00:00")
    cfg = _cfg(tmp_path)
    cfg["search"]["window_days"] = 30
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    paths = run_research(str(cfg_path))

    assert capsys.readouterr().out == ("time_window: kept=1 out_of_window=4 missing_time=0\n")
    note_rows = _csv_rows(Path(paths["notes"]))
    account_rows = _csv_rows(Path(paths["accounts"]))
    assert [row["note_id"] for row in note_rows] == ["6a3694f10000000017029511"]
    assert [row["account_id"] for row in account_rows] == ["66dd617b000000001d0215a6"]


def test_pipeline_end_to_end_with_comments(tmp_path, monkeypatch):
    monkeypatch.setattr("src.pipelines.run_research._now_iso", lambda: "2026")
    cfg = _cfg(tmp_path)
    cfg["comments"] = {
        "enabled": True,
        "limit": 10,
        "report_top_k": 3,
        "fixture_path": "tests/fixtures/comments.jsonl",
    }
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    paths = run_research(str(cfg_path))

    assert set(paths) == {
        "accounts",
        "notes",
        "account_rank",
        "typical_notes",
        "comments",
        "report_input",
    }
    with open(paths["comments"], encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["body", "note_id", "like_count", "collected_at"]
    assert rows[1][0].startswith("这个角度")
    assert rows[1][2] == "12000"

    md = Path(paths["report_input"]).read_text(encoding="utf-8")
    assert "评论 12000赞：这个角度很有帮助" in md
    run_dir = Path(paths["report_input"]).parent
    exported_text = "\n".join(
        p.read_text(encoding="utf-8") for p in run_dir.iterdir() if p.is_file()
    )
    assert "user-secret" not in exported_text
    assert "不应落盘" not in exported_text
    assert "avatar.example" not in exported_text


def test_pipeline_comments_disabled_matches_phase2_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr("src.pipelines.run_research._now_iso", lambda: "2026")
    base_dir = tmp_path / "base"
    disabled_dir = tmp_path / "disabled"
    base_cfg = _cfg(base_dir)
    disabled_cfg = _cfg(disabled_dir)
    disabled_cfg["comments"] = {
        "enabled": False,
        "limit": 10,
        "fixture_path": "tests/fixtures/comments.jsonl",
    }

    base_cfg_path = tmp_path / "base.yaml"
    disabled_cfg_path = tmp_path / "disabled.yaml"
    base_cfg_path.write_text(yaml.safe_dump(base_cfg, allow_unicode=True), encoding="utf-8")
    disabled_cfg_path.write_text(yaml.safe_dump(disabled_cfg, allow_unicode=True), encoding="utf-8")

    base_paths = run_research(str(base_cfg_path))
    disabled_paths = run_research(str(disabled_cfg_path))

    assert set(disabled_paths) == {
        "accounts",
        "notes",
        "account_rank",
        "typical_notes",
        "report_input",
    }
    assert not (disabled_dir / "comments.csv").exists()
    for key in disabled_paths:
        assert Path(disabled_paths[key]).read_bytes() == Path(base_paths[key]).read_bytes()


def test_pipeline_window_all_keep_and_decay_compares_note_id_projection(tmp_path, monkeypatch):
    monkeypatch.setattr("src.pipelines.run_research._now_iso", lambda: "2026-07-02T00:00:00+00:00")
    base_dir = tmp_path / "base"
    recency_dir = tmp_path / "recency"
    base_cfg = _cfg(base_dir)
    recency_cfg = _cfg(recency_dir)
    recency_cfg["search"]["window_days"] = 3650
    recency_cfg["selection"]["half_life_days"] = 14

    base_cfg_path = tmp_path / "base.yaml"
    recency_cfg_path = tmp_path / "recency.yaml"
    base_cfg_path.write_text(yaml.safe_dump(base_cfg, allow_unicode=True), encoding="utf-8")
    recency_cfg_path.write_text(yaml.safe_dump(recency_cfg, allow_unicode=True), encoding="utf-8")

    base_paths = run_research(str(base_cfg_path))
    recency_paths = run_research(str(recency_cfg_path))

    for key in ["accounts", "notes", "account_rank"]:
        assert Path(recency_paths[key]).read_bytes() == Path(base_paths[key]).read_bytes()
    # 半衰会改变 note_score/selection_reason/report 分数，按评审 #2 只比 note_id 投影。
    assert _typical_note_ids(Path(recency_paths["typical_notes"])) == _typical_note_ids(
        Path(base_paths["typical_notes"])
    )
    assert _report_note_ids(Path(recency_paths["report_input"])) == _report_note_ids(
        Path(base_paths["report_input"])
    )
