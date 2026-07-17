"""新入口的控制台与文件日志组装。"""

import logging
from pathlib import Path

from .runtime import compact_run_id

HANDLER_PREFIX = "xhsrecon."
FILE_FORMAT = (
    "%(asctime)s %(levelname)-7s %(name)s %(filename)s:%(lineno)d"
    " [%(provider)s %(run_id)s] %(message)s"
)


class ConsoleFormatter(logging.Formatter):
    def __init__(self):
        super().__init__("%(asctime)s %(mark)s%(message)s", datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        if record.levelno >= logging.ERROR:
            record.mark = "✖ "
        elif record.levelno >= logging.WARNING:
            record.mark = "⚠ "
        else:
            record.mark = ""
        line = super().format(record)
        if record.levelno >= logging.WARNING:
            line += f" · {record.filename}:{record.lineno}"
        return line


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
    return getattr(logging, str(value or "info").upper(), logging.INFO)


def _remove_own_handlers(root: logging.Logger) -> None:
    for handler in list(root.handlers):
        if (handler.name or "").startswith(HANDLER_PREFIX):
            root.removeHandler(handler)
            handler.close()


def configure_logging(cfg: dict | None, *, verbose: bool, run_id: str, provider: str) -> None:
    cfg = cfg or {}
    root = logging.getLogger()
    _remove_own_handlers(root)
    root.setLevel(logging.DEBUG)
    context = RunContextFilter(run_id, provider)

    console = logging.StreamHandler()
    console.set_name(f"{HANDLER_PREFIX}console")
    console.setLevel(logging.DEBUG if verbose else _level(cfg.get("level")))
    console.setFormatter(ConsoleFormatter())
    console.addFilter(context)
    root.addHandler(console)

    log_path = None
    if cfg.get("file_enabled", True):
        log_dir = Path(cfg.get("dir", "data/logs"))
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"run-{compact_run_id(run_id)}.log"
            handler = logging.FileHandler(log_path, encoding="utf-8")
        except OSError as exc:
            logging.getLogger(__name__).warning("文件日志不可用：%s（仅控制台输出）", exc)
        else:
            handler.set_name(f"{HANDLER_PREFIX}file")
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(logging.Formatter(FILE_FORMAT))
            handler.addFilter(context)
            root.addHandler(handler)

    message = "▶ 开始运行 · 数据源 %s"
    args = [provider]
    if log_path:
        message += " · 全量日志 %s"
        args.append(log_path)
    logging.getLogger(__name__).info(message, *args)
