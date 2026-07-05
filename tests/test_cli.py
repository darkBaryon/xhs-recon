"""cli 子命令：research 与旧入口逐字节等价；search/sync/comments 分工与补全写回口径。"""

from pathlib import Path

import yaml
from typer.testing import CliRunner

from src.pipelines.cli import app
from src.pipelines.run_research import run_research

runner = CliRunner()

PIN = "2026"  # 既有 e2e pin 手法（window_days=0 配置下合法）


def _cfg(out_dir: Path, *, watchlist: bool = True, comments: bool = True) -> dict:
    cfg = {
        "provider": "fixture",
        "fixture_path": "tests/fixtures/search_contents_sample.jsonl",
        "creator_fixture_path": "tests/fixtures/creator_contents_sample.jsonl",
        "keywords": ["留学辅导"],
        "search": {"pages": 1, "limit": 20, "sort": "", "window_days": 0},
        "selection": {"top_notes_per_account": 2, "half_life_days": 0},
        "logging": {"file_enabled": False},
        "export": {"out_dir": str(out_dir)},
        "comments": {
            "enabled": comments,
            "limit": 10,
            "report_top_k": 3,
            "fixture_path": "tests/fixtures/comments.jsonl",
        },
    }
    if watchlist:
        cfg["watchlist"] = {
            "auto_top_n": 1,
            "manual": ["601d0481000000000101cc46"],
            "max_total": 5,
        }
        cfg["creator"] = {"notes_per_account": 3}
    return cfg


def _write_cfg(tmp_path: Path, name: str, cfg: dict) -> str:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return str(p)


def _pin(monkeypatch):
    monkeypatch.setattr("src.pipelines.runtime.now_iso", lambda: PIN)


def _run_dir(out_dir: Path) -> Path:
    # 经 latest 软链定位真实运行目录（未 pin 的用例 run_id 是真实时间戳）
    return (out_dir / "latest").resolve()


def _snapshot(run_dir: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(run_dir.iterdir()) if p.is_file()}


def test_cli_research_matches_old_entry(tmp_path, monkeypatch):
    _pin(monkeypatch)
    old_out, new_out = tmp_path / "old", tmp_path / "new"
    run_research(_write_cfg(tmp_path, "old.yaml", _cfg(old_out)))
    result = runner.invoke(
        app, ["research", "--config", _write_cfg(tmp_path, "new.yaml", _cfg(new_out))]
    )
    assert result.exit_code == 0

    old_files = _snapshot(_run_dir(old_out))
    new_files = _snapshot(_run_dir(new_out))
    assert old_files.keys() == new_files.keys()
    for name in old_files:
        assert old_files[name] == new_files[name], f"{name} 字节不一致"


def test_cli_search_produces_only_search_side(tmp_path):
    out = tmp_path / "out"
    result = runner.invoke(app, ["search", "--config", _write_cfg(tmp_path, "c.yaml", _cfg(out))])
    assert result.exit_code == 0
    names = set(_snapshot(_run_dir(out)))
    assert {
        "accounts.csv",
        "notes.csv",
        "account_rank.csv",
        "typical_notes.csv",
        "report_input.md",
    } <= names
    # 不采评论、不产 watchlist 侧四件（即便 config 配了对应段）
    assert names.isdisjoint(
        {
            "comments.csv",
            "watchlist.csv",
            "creator_notes.csv",
            "account_profile.csv",
            "topic_feed.md",
            "topic_feed.jsonl",
        }
    )
    assert (out / "latest").is_symlink()  # search 建目录并维护 latest


def test_cli_sync_backfills_latest_run_dir(tmp_path):
    out = tmp_path / "out"
    cfg_path = _write_cfg(tmp_path, "c.yaml", _cfg(out))
    assert runner.invoke(app, ["search", "--config", cfg_path]).exit_code == 0
    before = _snapshot(_run_dir(out))

    result = runner.invoke(app, ["sync", "--config", cfg_path])
    assert result.exit_code == 0
    after = _snapshot(_run_dir(out))

    # 同一目录补齐 watchlist 侧文件（含档案，jsonl+md 各算一名）
    added = set(after) - set(before)
    assert added == {
        "watchlist.csv",
        "creator_notes.csv",
        "account_profile.csv",
        "topic_feed.md",
        "topic_feed.jsonl",
        "creator_profiles.csv",
    }
    # 旧文件字节不变（评审 #1 阻塞1 的回归锁）
    for name in before:
        assert after[name] == before[name], f"{name} 被 sync 改动"
    # manual 账号进了 watchlist
    assert b"601d0481000000000101cc46" in after["watchlist.csv"]


def test_cli_sync_without_any_run_exits(tmp_path):
    cfg_path = _write_cfg(tmp_path, "c.yaml", _cfg(tmp_path / "out"))
    result = runner.invoke(app, ["sync", "--config", cfg_path])
    assert result.exit_code == 1


def test_cli_sync_missing_rank_degrades_to_manual_only(tmp_path):
    out = tmp_path / "out"
    cfg_path = _write_cfg(tmp_path, "c.yaml", _cfg(out))
    assert runner.invoke(app, ["search", "--config", cfg_path]).exit_code == 0
    (_run_dir(out) / "account_rank.csv").unlink()

    result = runner.invoke(app, ["sync", "--config", cfg_path])
    assert result.exit_code == 0
    watch = (_run_dir(out) / "watchlist.csv").read_text(encoding="utf-8")
    assert "auto" not in watch  # 榜单缺失 → 无 auto 名额
    assert "manual" in watch


def test_cli_comments_backfills_report_and_keeps_others(tmp_path):
    out = tmp_path / "out"
    cfg_path = _write_cfg(tmp_path, "c.yaml", _cfg(out))
    assert runner.invoke(app, ["search", "--config", cfg_path]).exit_code == 0
    assert runner.invoke(app, ["sync", "--config", cfg_path]).exit_code == 0
    before = _snapshot(_run_dir(out))

    result = runner.invoke(app, ["comments", "--config", cfg_path])
    assert result.exit_code == 0
    after = _snapshot(_run_dir(out))

    assert set(after) - set(before) == {"comments.csv"}
    assert after["report_input.md"] != before["report_input.md"]  # 织入评论后重写
    assert "评论".encode() in after["report_input.md"]
    changed = {n for n in before if after[n] != before[n]}
    assert changed == {"report_input.md"}  # 其余文件字节不变


def test_cli_comments_without_run_exits(tmp_path):
    cfg_path = _write_cfg(tmp_path, "c.yaml", _cfg(tmp_path / "out"))
    assert runner.invoke(app, ["comments", "--config", cfg_path]).exit_code == 1


def test_cli_comments_respects_enabled_flag(tmp_path):
    """现行为回归锁（实施偏差4，待用户裁决）：enabled=false 时显式 cli comments 也不采集。"""
    out = tmp_path / "out"
    cfg_path = _write_cfg(tmp_path, "c.yaml", _cfg(out, comments=False))
    assert runner.invoke(app, ["search", "--config", cfg_path]).exit_code == 0

    result = runner.invoke(app, ["comments", "--config", cfg_path])
    assert result.exit_code == 0
    names = set(_snapshot(_run_dir(out)))
    assert "comments.csv" not in names  # 开关拦下，未采集


def test_full_chain_search_sync_comments(tmp_path):
    """推荐链路端到端：三命令顺序执行全通，产物聚在同一运行目录。"""
    out = tmp_path / "out"
    cfg_path = _write_cfg(tmp_path, "c.yaml", _cfg(out))
    for cmd in ["search", "sync", "comments"]:
        assert runner.invoke(app, [cmd, "--config", cfg_path]).exit_code == 0, cmd
    names = set(_snapshot(_run_dir(out)))
    assert {
        "accounts.csv",
        "notes.csv",
        "account_rank.csv",
        "typical_notes.csv",
        "report_input.md",
        "watchlist.csv",
        "creator_notes.csv",
        "account_profile.csv",
        "topic_feed.md",
        "topic_feed.jsonl",
        "comments.csv",
    } <= names


class _CaptureCommentsAdapter:
    """B3 用：记录 fetch_comments 实际收到的典型笔记数。"""

    def __init__(self, inner):
        self._inner = inner
        self.seen: list[int] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def fetch_comments(self, notes, limit, collected_at):
        self.seen.append(len(notes))
        return self._inner.fetch_comments(notes, limit, collected_at)


def test_comments_stage_caps_typical_notes(monkeypatch):
    """B3：典型笔记超 comments.max_notes 时按分数截前 N 采评论（实测 119 条必超时的修复）。"""
    from src.adapters.fixture_adapter import FixtureAdapter
    from src.models import TypicalNote
    from src.pipelines.config import RunConfig
    from src.pipelines.run_research import _comments_stage

    adapter = _CaptureCommentsAdapter(
        FixtureAdapter(
            "tests/fixtures/search_contents_sample.jsonl",
            comments_path="tests/fixtures/comments.jsonl",
        )
    )
    typical = [
        TypicalNote(
            account_id="a",
            note_id=f"n{i}",
            title="t",
            url=f"https://example.com/n{i}",
            note_score=float(i),
            selection_reason="top",
        )
        for i in range(10)
    ]
    cfg = RunConfig.model_validate({"comments": {"enabled": True, "limit": 5, "max_notes": 3}})
    _comments_stage(cfg, adapter, typical, "2026")
    assert adapter.seen == [3]  # 只送前 3 条（按 note_score 降序）


def test_cli_sync_produces_creator_profiles(tmp_path):
    """档案落盘 e2e：sync 后同目录多出 creator_profiles.csv，旧文件字节不变。"""
    out = tmp_path / "out"
    cfg = _cfg(out)
    cfg["creator_profiles_fixture_path"] = "tests/fixtures/creator_creators_sample.jsonl"
    cfg_path = _write_cfg(tmp_path, "c.yaml", cfg)
    assert runner.invoke(app, ["search", "--config", cfg_path]).exit_code == 0
    before = _snapshot(_run_dir(out))

    assert runner.invoke(app, ["sync", "--config", cfg_path]).exit_code == 0
    after = _snapshot(_run_dir(out))

    assert "creator_profiles.csv" in set(after) - set(before)
    for name in before:
        assert after[name] == before[name], f"{name} 被 sync 改动"
    # 601d... 在 watchlist manual + 档案夹具里 → 有档案行
    assert b"601d0481000000000101cc46" in after["creator_profiles.csv"]
