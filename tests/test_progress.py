"""progress 显示层：非 TTY 静默（no-op 不输出）；TTY（注入 force_terminal）画条不炸。"""

import io

from rich.console import Console

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
