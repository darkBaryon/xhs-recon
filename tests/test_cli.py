"""cli 子命令：research 与旧入口逐字节等价；search/track/comments 分工与写回口径。"""

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
        }
    )
    assert (out / "latest").is_symlink()  # search 建目录并维护 latest


def test_cli_track_backfills_search_run_dir(tmp_path):
    out = tmp_path / "out"
    cfg_path = _write_cfg(tmp_path, "c.yaml", _cfg(out))
    assert runner.invoke(app, ["search", "--config", cfg_path]).exit_code == 0
    before = _snapshot(_run_dir(out))

    result = runner.invoke(app, ["track", "--config", cfg_path])
    assert result.exit_code == 0
    after = _snapshot(_run_dir(out))

    # 同一目录补齐 watchlist 侧文件（含档案，jsonl+md 各算一名）
    added = set(after) - set(before)
    assert added == {
        "watchlist.csv",
        "creator_notes.csv",
        "account_profile.csv",
        "creator_profiles.csv",
    }
    # 旧文件字节不变（评审 #1 阻塞1 的回归锁）
    for name in before:
        assert after[name] == before[name], f"{name} 被 track 改动"
    # manual 账号进了 watchlist
    assert b"601d0481000000000101cc46" in after["watchlist.csv"]


def test_cli_track_standalone_self_builds_run_dir(tmp_path):
    # 无任何 search：track 自建运行目录独立跑（解耦「必须先 search」）
    out = tmp_path / "out"
    cfg_path = _write_cfg(tmp_path, "c.yaml", _cfg(out))
    result = runner.invoke(app, ["track", "--config", cfg_path])
    assert result.exit_code == 0, result.output
    run_dir = _run_dir(out)
    names = set(_snapshot(run_dir))
    # 只产 watchlist 侧、无 search 产物
    assert "watchlist.csv" in names
    assert names.isdisjoint({"accounts.csv", "notes.csv", "account_rank.csv"})
    # manual 账号在；无榜单 → auto 名额降级
    watch = (run_dir / "watchlist.csv").read_text(encoding="utf-8")
    assert "601d0481000000000101cc46" in watch
    assert "auto" not in watch


def test_cli_track_rerun_archives_new_run_dir(tmp_path, monkeypatch):
    # 已 track 过的 latest 再跑 track → 自建新目录逐次归档，旧目录不动（日常盯人工作流）
    import itertools

    counter = itertools.count(1)
    monkeypatch.setattr(
        "src.pipelines.runtime.now_iso", lambda: f"2026-01-{next(counter):02d}T00:00:00"
    )
    out = tmp_path / "out"
    cfg_path = _write_cfg(tmp_path, "c.yaml", _cfg(out))
    assert runner.invoke(app, ["search", "--config", cfg_path]).exit_code == 0
    assert runner.invoke(app, ["track", "--config", cfg_path]).exit_code == 0
    first_dir = _run_dir(out)
    assert (first_dir / "watchlist.csv").exists()  # 已 track（补全写回 search 目录）

    assert runner.invoke(app, ["track", "--config", cfg_path]).exit_code == 0
    second_dir = _run_dir(out)
    assert second_dir != first_dir  # 归档到新目录
    assert (second_dir / "watchlist.csv").exists()
    assert first_dir.exists()  # 旧目录保留
    assert not (second_dir / "notes.csv").exists()  # 新目录纯 watchlist 侧

    # 第三次 track：latest 已是无榜单的自建目录，auto 名额须回溯最近 search，不得静默清空
    assert runner.invoke(app, ["track", "--config", cfg_path]).exit_code == 0
    third_dir = _run_dir(out)
    assert third_dir not in (first_dir, second_dir)
    watch = (third_dir / "watchlist.csv").read_text(encoding="utf-8")
    assert "auto" in watch  # 榜单回溯成功，auto 名额仍在
    assert "601d0481000000000101cc46" in watch  # manual 也在


def test_cli_track_missing_rank_degrades_to_manual_only(tmp_path):
    out = tmp_path / "out"
    cfg_path = _write_cfg(tmp_path, "c.yaml", _cfg(out))
    assert runner.invoke(app, ["search", "--config", cfg_path]).exit_code == 0
    (_run_dir(out) / "account_rank.csv").unlink()

    result = runner.invoke(app, ["track", "--config", cfg_path])
    assert result.exit_code == 0
    watch = (_run_dir(out) / "watchlist.csv").read_text(encoding="utf-8")
    assert "auto" not in watch  # 榜单缺失 → 无 auto 名额
    assert "manual" in watch


def test_full_chain_search_track(tmp_path):
    """推荐链路端到端：search + track 顺序执行全通（评论已随 track 抓回，无单独 comments 命令）。"""
    out = tmp_path / "out"
    cfg_path = _write_cfg(tmp_path, "c.yaml", _cfg(out))
    for cmd in ["search", "track"]:
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
    } <= names


def test_comments_folded_into_creator_fetch():
    """全量采集：评论随 creator 一同带回（FetchResult.comments 非空），不再走单独命令。"""
    from src.adapters.fixture_adapter import FixtureAdapter

    adapter = FixtureAdapter(
        "tests/fixtures/search_contents_sample.jsonl",
        creator_path="tests/fixtures/creator_contents_sample.jsonl",
        comments_path="tests/fixtures/comments.jsonl",
    )
    r = adapter.fetch_creator_notes(["601d0481000000000101cc46"], 3, "2026")
    assert r.ok
    assert len(r.comments) >= 1  # 评论随 creator 结果一并返回


def test_cli_track_produces_creator_profiles(tmp_path):
    """档案落盘 e2e：sync 后同目录多出 creator_profiles.csv，旧文件字节不变。"""
    out = tmp_path / "out"
    cfg = _cfg(out)
    cfg["creator_profiles_fixture_path"] = "tests/fixtures/creator_creators_sample.jsonl"
    cfg_path = _write_cfg(tmp_path, "c.yaml", cfg)
    assert runner.invoke(app, ["search", "--config", cfg_path]).exit_code == 0
    before = _snapshot(_run_dir(out))

    assert runner.invoke(app, ["track", "--config", cfg_path]).exit_code == 0
    after = _snapshot(_run_dir(out))

    assert "creator_profiles.csv" in set(after) - set(before)
    for name in before:
        assert after[name] == before[name], f"{name} 被 sync 改动"
    # 601d... 在 watchlist manual + 档案夹具里 → 有档案行
    assert b"601d0481000000000101cc46" in after["creator_profiles.csv"]


def test_cli_track_loop_rotates_until_no_due_accounts(tmp_path, monkeypatch):
    """--loop：批批推进，满批→休眠继续，空批→自动收工（伪 store/伪 sync 段）。"""
    from src.models import WatchAccount
    from src.pipelines.run_research import SyncArtifacts

    out = tmp_path / "out"
    cfg = _cfg(out)
    cfg["creator"]["batch_size"] = 1
    cfg_path = _write_cfg(tmp_path, "c.yaml", cfg)

    monkeypatch.setattr("src.pipelines.runtime.build_store", lambda config: object())
    batches = [
        [WatchAccount(account_id="a1", source="manual")],  # 满批（=batch_size）→ 继续
        [],  # 空批 → 收工
    ]
    calls = []

    def fake_sync(cfg_, adapter, collected_at, ranks, store=None):
        calls.append(store)
        return SyncArtifacts(watchlist=batches[len(calls) - 1])

    monkeypatch.setattr("src.pipelines.run_research._sync_stage", fake_sync)
    sleeps = []
    monkeypatch.setattr("src.pipelines.cli.time.sleep", lambda s: sleeps.append(s))

    result = runner.invoke(
        app,
        ["track", "--config", cfg_path, "--loop", "--pause-min", "7", "--pause-max", "7"],
    )

    assert result.exit_code == 0, result.output
    assert len(calls) == 2  # 第二批后停：没有第三批
    assert sleeps == [7]  # 只在两批之间休眠一次


def test_cli_track_loop_stops_early_on_partial_batch(tmp_path, monkeypatch):
    """--loop：批量不足 batch_size = 到期账号已抓完 → 不再多睡一轮直接收工。"""
    from src.models import WatchAccount
    from src.pipelines.run_research import SyncArtifacts

    out = tmp_path / "out"
    cfg = _cfg(out)
    cfg["creator"]["batch_size"] = 5
    cfg_path = _write_cfg(tmp_path, "c.yaml", cfg)

    monkeypatch.setattr("src.pipelines.runtime.build_store", lambda config: object())

    def fake_sync(cfg_, adapter, collected_at, ranks, store=None):
        # 只回 2 个（< batch_size=5），且 self 不占轮转名额
        return SyncArtifacts(
            watchlist=[
                WatchAccount(account_id="me", source="self"),
                WatchAccount(account_id="a1", source="manual"),
                WatchAccount(account_id="a2", source="auto"),
            ]
        )

    monkeypatch.setattr("src.pipelines.run_research._sync_stage", fake_sync)
    sleeps = []
    monkeypatch.setattr("src.pipelines.cli.time.sleep", lambda s: sleeps.append(s))

    result = runner.invoke(app, ["track", "--config", cfg_path, "--loop"])

    assert result.exit_code == 0, result.output
    assert sleeps == []  # 尾批直接收工，零休眠


def test_cli_track_loop_without_store_runs_once(tmp_path, monkeypatch):
    """--loop 但 store 未启用：警告并只跑一批（无轮转状态，循环无意义）。"""
    result_cfg = _write_cfg(tmp_path, "c.yaml", _cfg(tmp_path / "out"))
    sleeps = []
    monkeypatch.setattr("src.pipelines.cli.time.sleep", lambda s: sleeps.append(s))

    result = runner.invoke(app, ["track", "--config", result_cfg, "--loop"])

    assert result.exit_code == 0, result.output
    assert sleeps == []
