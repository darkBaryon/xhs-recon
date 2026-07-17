import io

from rich.console import Console

from src.recon.entrypoints import progress_ui


def _console(terminal: bool):
    buffer = io.StringIO()
    console = Console(
        file=buffer,
        force_terminal=terminal,
        force_interactive=terminal,
        width=80,
        _environ={"TERM": "xterm-256color"},
    )
    return buffer, console


def test_progress_ui_is_silent_without_tty():
    buffer, console = _console(False)

    with progress_ui.creator_progress(2, console=console) as callback:
        assert callback is None
    with progress_ui.search_progress(2, console=console) as callback:
        assert callback is None
    with progress_ui.detail_progress(2, console=console) as callback:
        assert callback is None
    with progress_ui.spinner("处理中", console=console):
        pass

    assert buffer.getvalue() == ""


def test_progress_ui_translates_search_and_detail_events_on_tty():
    buffer, console = _console(True)

    with progress_ui.search_progress(1, 2, console) as callback:
        assert callback is not None
        callback({"kind": "keyword_start", "index": 1, "keyword": "留学辅导"})
        callback({"kind": "page_start", "keyword": "留学辅导", "page": 1})
        callback({"kind": "note"})
        callback({"kind": "done"})
    with progress_ui.detail_progress(1, console) as callback:
        assert callback is not None
        callback({"kind": "note"})
        callback({"kind": "comments"})

    output = buffer.getvalue()
    assert "留学辅导" in output
    assert "新帖正文/图" in output
    assert "新帖评论" in output
