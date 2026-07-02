"""Pipeline logging assembly helpers.

Only pipeline entrypoints configure logging. Core and adapters should use plain
``logging.getLogger(__name__)`` and never import this module.
"""

import logging
from pathlib import Path

from src.models import FetchResult

HANDLER_PREFIX = "xhsrecon."
FORMAT = "%(asctime)s %(levelname)-7s %(name)s [%(provider)s %(run_id)s] %(message)s"


class RunContextFilter(logging.Filter):
    def __init__(self, run_id: str, provider: str):
        super().__init__()
        self.run_id = run_id
        self.provider = provider

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self.run_id
        record.provider = self.provider
        return True


def _level(value: str | None) -> int:
    if not value:
        return logging.INFO
    return getattr(logging, str(value).upper(), logging.INFO)


def _remove_own_handlers(root: logging.Logger) -> None:
    for handler in list(root.handlers):
        name = handler.name or ""
        if name.startswith(HANDLER_PREFIX):
            root.removeHandler(handler)
            handler.close()


def configure_logging(cfg: dict | None, *, verbose: bool, run_id: str, provider: str) -> None:
    cfg = cfg or {}
    root = logging.getLogger()
    _remove_own_handlers(root)
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(FORMAT)
    context_filter = RunContextFilter(run_id, provider)

    console = logging.StreamHandler()
    console.set_name(f"{HANDLER_PREFIX}console")
    console.setLevel(logging.DEBUG if verbose else _level(cfg.get("level", "info")))
    console.setFormatter(formatter)
    console.addFilter(context_filter)
    root.addHandler(console)

    if cfg.get("file_enabled", True) is False:
        return

    log_dir = Path(cfg.get("dir", "data/logs"))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / f"run-{run_id}.log", encoding="utf-8")
    except OSError as e:
        logging.getLogger(__name__).warning("file logging disabled: %s", e)
        return

    file_handler.set_name(f"{HANDLER_PREFIX}file")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(context_filter)
    root.addHandler(file_handler)


def log_result(logger: logging.Logger, fr: FetchResult) -> None:
    if fr.ok:
        logger.info(
            "%s ok: %d notes %d accounts %d comments",
            fr.operation,
            len(fr.notes),
            len(fr.accounts),
            len(fr.comments),
        )
        return
    logger.warning("%s failed: %s", fr.operation, fr.error)
