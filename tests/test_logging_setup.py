import logging

from src.models import FetchResult
from src.pipelines.logging_setup import HANDLER_PREFIX, configure_logging, log_result


def _own_handlers():
    root = logging.getLogger()
    return [h for h in root.handlers if (h.name or "").startswith(HANDLER_PREFIX)]


def test_configure_logging_creates_console_and_file_handlers(tmp_path):
    configure_logging(
        {"level": "warning", "dir": str(tmp_path), "file_enabled": True},
        verbose=False,
        run_id="run-1",
        provider="fixture",
    )

    handlers = _own_handlers()
    assert {h.name for h in handlers} == {"xhsrecon.console", "xhsrecon.file"}
    assert next(h for h in handlers if h.name == "xhsrecon.console").level == logging.WARNING
    assert next(h for h in handlers if h.name == "xhsrecon.file").level == logging.DEBUG
    assert (tmp_path / "run-run-1.log").exists()


def test_configure_logging_verbose_forces_console_debug(tmp_path):
    configure_logging(
        {"level": "error", "dir": str(tmp_path)},
        verbose=True,
        run_id="run-verbose",
        provider="fixture",
    )

    console = next(h for h in _own_handlers() if h.name == "xhsrecon.console")
    assert console.level == logging.DEBUG


def test_configure_logging_file_can_be_disabled(tmp_path):
    configure_logging(
        {"dir": str(tmp_path), "file_enabled": False},
        verbose=False,
        run_id="run-no-file",
        provider="fixture",
    )

    assert {h.name for h in _own_handlers()} == {"xhsrecon.console"}
    assert not (tmp_path / "run-run-no-file.log").exists()


def test_configure_logging_idempotent_keeps_stranger_handler(tmp_path):
    root = logging.getLogger()
    stranger = logging.StreamHandler()
    stranger.set_name("pytest_caplog_handler")
    root.addHandler(stranger)
    try:
        configure_logging(
            {"dir": str(tmp_path)},
            verbose=False,
            run_id="run-a",
            provider="fixture",
        )
        configure_logging(
            {"dir": str(tmp_path)},
            verbose=True,
            run_id="run-b",
            provider="fixture",
        )

        assert stranger in root.handlers
        assert {h.name for h in _own_handlers()} == {"xhsrecon.console", "xhsrecon.file"}
    finally:
        root.removeHandler(stranger)


def test_run_context_fields_written_to_file(tmp_path):
    configure_logging(
        {"dir": str(tmp_path)},
        verbose=True,
        run_id="run-fields",
        provider="fixture",
    )

    logging.getLogger("tests.logging_setup").debug("hello")
    for handler in _own_handlers():
        handler.flush()

    text = (tmp_path / "run-run-fields.log").read_text(encoding="utf-8")
    assert "[fixture run-fields] hello" in text


def test_log_result_routes_ok_and_error(caplog):
    logger = logging.getLogger("tests.log_result")
    ok = FetchResult(provider="fixture", operation="search", collected_at="2026", notes=[])
    bad = FetchResult(
        provider="fixture", operation="fetch_comments", collected_at="2026", error="boom"
    )

    with caplog.at_level(logging.INFO):
        log_result(logger, ok)
        log_result(logger, bad)

    assert "search ok: 0 notes 0 accounts 0 comments" in caplog.text
    assert "fetch_comments failed: boom" in caplog.text
    assert any(r.levelno == logging.WARNING for r in caplog.records)
