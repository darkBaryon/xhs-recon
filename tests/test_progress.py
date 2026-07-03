"""progress 显示层：非 TTY 静默（no-op 不输出）；TTY（注入 force_terminal）画条不炸。"""

import io
from contextlib import contextmanager

from rich.console import Console

import src.pipelines.run_research as run_research
from src.models import FetchResult
from src.pipelines import progress


def _tty_console(buf: io.StringIO) -> Console:
    return Console(file=buf, force_terminal=True, width=80)


def _non_tty_console(buf: io.StringIO) -> Console:
    return Console(file=buf, force_terminal=False, width=80)


# ---- 非 TTY：全部 no-op、零输出 ----


def test_stage_bar_non_tty_silent():
    buf = io.StringIO()
    with progress.stage_bar("搜索", total=3, console=_non_tty_console(buf)) as bar:
        bar.describe("搜索「留学」")
        bar.advance()
    assert buf.getvalue() == ""


def test_creator_progress_non_tty_yields_none():
    buf = io.StringIO()
    with progress.creator_progress(5, console=_non_tty_console(buf)) as cb:
        assert cb is None
    assert buf.getvalue() == ""


def test_spinner_non_tty_silent():
    buf = io.StringIO()
    with progress.spinner("评论采集中", console=_non_tty_console(buf)):
        pass
    assert buf.getvalue() == ""


def test_stage_bar_zero_total_is_noop_even_on_tty():
    buf = io.StringIO()
    with progress.stage_bar("搜索", total=0, console=_tty_console(buf)) as bar:
        bar.advance()
    assert buf.getvalue() == ""


# ---- TTY（force_terminal 注入）：正常画、事件驱动更新、不抛异常 ----


def test_stage_bar_tty_renders_description():
    buf = io.StringIO()
    with progress.stage_bar("搜索", total=2, console=_tty_console(buf)) as bar:
        bar.describe("搜索「留学辅导」")
        bar.advance()
        bar.describe("搜索「essay」")
        bar.advance()
    out = buf.getvalue()
    assert "留学辅导" in out
    assert "1/2" in out


def test_creator_progress_tty_translates_events():
    buf = io.StringIO()
    names = {"u1": "机构A"}
    with progress.creator_progress(3, names=names, console=_tty_console(buf)) as cb:
        assert cb is not None
        cb({"kind": "creator_start", "index": 1, "user_id": "u1"})
        cb({"kind": "note", "count": 1})
        cb({"kind": "note", "count": 2})
        # names 没有的 id 显示原 id
        cb({"kind": "creator_start", "index": 2, "user_id": "u2"})
        # 未知事件类型：忽略不炸（adapter 将来加事件不破坏旧显示层）
        cb({"kind": "future_event"})
    out = buf.getvalue()
    assert "机构A" in out
    assert "笔记 2" in out
    assert "u2" in out


def test_spinner_tty_shows_status():
    buf = io.StringIO()
    with progress.spinner("评论采集：30 条", console=_tty_console(buf)):
        pass
    assert "评论采集" in buf.getvalue()


# ---- 管线接线：_sync_stage 对支持进度的 adapter 注入回调、用完复位 ----


class _StubProgressAdapter:
    """有 on_progress 属性 = 支持进度事件（与 MediaCrawlerAdapter 同约定）。"""

    provider_name = "stub"

    def __init__(self):
        self.on_progress = None
        self.callback_during_fetch = "unset"

    def fetch_creator_notes(self, account_ids, limit, collected_at):
        self.callback_during_fetch = self.on_progress
        return FetchResult(
            provider=self.provider_name,
            operation="creator_notes",
            collected_at=collected_at,
        )


def test_sync_stage_injects_and_resets_progress_callback(monkeypatch):
    def sentinel_cb(event):
        pass

    @contextmanager
    def fake_creator_progress(total, names=None, console=None):
        assert total == 1
        yield sentinel_cb  # 模拟 TTY：给出真回调

    monkeypatch.setattr(progress, "creator_progress", fake_creator_progress)
    adapter = _StubProgressAdapter()
    config = {"watchlist": {"manual": ["601d0481000000000101cc46"]}}

    run_research._sync_stage(config, adapter, "2026-07-03T00:00:00Z", [])

    assert adapter.callback_during_fetch is sentinel_cb  # 采集期间已注入
    assert adapter.on_progress is None  # 用完复位


def test_sync_stage_non_tty_leaves_adapter_callback_unset(monkeypatch):
    @contextmanager
    def fake_creator_progress(total, names=None, console=None):
        yield None  # 模拟非 TTY

    monkeypatch.setattr(progress, "creator_progress", fake_creator_progress)
    adapter = _StubProgressAdapter()
    config = {"watchlist": {"manual": ["601d0481000000000101cc46"]}}

    run_research._sync_stage(config, adapter, "2026-07-03T00:00:00Z", [])

    assert adapter.callback_during_fetch is None  # 非 TTY：不注入，零回调开销
