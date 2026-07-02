"""Pipeline logging assembly helpers.

Only pipeline entrypoints configure logging. Core and adapters should use plain
``logging.getLogger(__name__)`` and never import this module.

控制台与文件双格式：控制台给人看（短时间+级别+消息，run 上下文由开头的
"run ..." 头行交代）；文件给复盘用（全量字段 [provider run_id]）。
"""

import logging
import re
from pathlib import Path

from src.models import FetchResult

HANDLER_PREFIX = "xhsrecon."
CONSOLE_FORMAT = "%(asctime)s %(levelname)-5s %(message)s"
CONSOLE_DATEFMT = "%H:%M:%S"
FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s [%(provider)s %(run_id)s] %(message)s"


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


def _compact_run_id(run_id: str) -> str:
    """ISO run_id → 文件名安全压缩形：去微秒/时区，只留数字与 T（如 20260702T105830）。"""
    base = run_id.split(".")[0].split("+")[0]
    return re.sub(r"[^0-9A-Za-zT]", "", base) or "run"


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

    context_filter = RunContextFilter(run_id, provider)

    console = logging.StreamHandler()
    console.set_name(f"{HANDLER_PREFIX}console")
    console.setLevel(logging.DEBUG if verbose else _level(cfg.get("level", "info")))
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt=CONSOLE_DATEFMT))
    console.addFilter(context_filter)
    root.addHandler(console)

    if cfg.get("file_enabled", True):
        log_dir = Path(cfg.get("dir", "data/logs"))
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(
                log_dir / f"run-{_compact_run_id(run_id)}.log", encoding="utf-8"
            )
        except OSError as e:
            logging.getLogger(__name__).warning("file logging disabled: %s", e)
        else:
            file_handler.set_name(f"{HANDLER_PREFIX}file")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
            file_handler.addFilter(context_filter)
            root.addHandler(file_handler)

    # 头行：控制台短格式下的 run 上下文交代（文件里每行本就带 [provider run_id]）
    logging.getLogger(__name__).info("run %s provider=%s", run_id.split(".")[0], provider)


def log_result(logger: logging.Logger, fr: FetchResult) -> None:
    # 成功走 DEBUG：阶段行（INFO）已含同等信息，避免控制台每步两行重复。
    if fr.ok:
        logger.debug(
            "%s ok: %d notes %d accounts %d comments",
            fr.operation,
            len(fr.notes),
            len(fr.accounts),
            len(fr.comments),
        )
        return
    logger.warning("%s failed: %s", fr.operation, fr.error)
