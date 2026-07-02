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
CONSOLE_DATEFMT = "%H:%M:%S"
FILE_FORMAT = (
    "%(asctime)s %(levelname)-7s %(name)s %(filename)s:%(lineno)d"
    " [%(provider)s %(run_id)s] %(message)s"
)

# 评论采集等操作名 → 人话（log_result 失败行用）
_OP_CN = {"search": "搜索", "fetch_comments": "评论采集", "creator_notes": "创作者笔记采集"}


class ConsoleFormatter(logging.Formatter):
    """控制台人读格式：时分秒 + 消息；成功不带级别字样，WARNING 以上带醒目标记。"""

    def __init__(self):
        super().__init__("%(asctime)s %(mark)s%(message)s", datefmt=CONSOLE_DATEFMT)

    def format(self, record: logging.LogRecord) -> str:
        if record.levelno >= logging.ERROR:
            record.mark = "✖ "
        elif record.levelno >= logging.WARNING:
            record.mark = "⚠ "
        else:
            record.mark = ""
        line = super().format(record)
        if record.levelno >= logging.WARNING:
            # 警告以上带出处，便于定位（成功路径不加，保持叙事干净）
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
    console.setFormatter(ConsoleFormatter())
    console.addFilter(context_filter)
    root.addHandler(console)

    log_path = None
    if cfg.get("file_enabled", True):
        log_dir = Path(cfg.get("dir", "data/logs"))
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"run-{_compact_run_id(run_id)}.log"
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
        except OSError as e:
            log_path = None
            logging.getLogger(__name__).warning("文件日志不可用：%s（仅控制台输出）", e)
        else:
            file_handler.set_name(f"{HANDLER_PREFIX}file")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
            file_handler.addFilter(context_filter)
            root.addHandler(file_handler)

    # 头行：控制台短格式下的 run 上下文交代（文件里每行本就带 [provider run_id]）；
    # 同时预告全量日志位置——报错时知道去哪翻。
    if log_path:
        logging.getLogger(__name__).info("▶ 开始运行 · 数据源 %s · 全量日志 %s", provider, log_path)
    else:
        logging.getLogger(__name__).info("▶ 开始运行 · 数据源 %s", provider)


def log_result(logger: logging.Logger, fr: FetchResult) -> None:
    # 成功走 DEBUG：阶段行（INFO）已含同等信息，避免控制台每步两行重复。
    # stacklevel=2：日志出处指向调用现场（run_research 的那一行），而非本帮手函数
    if fr.command:
        logger.debug("%s command: %s", fr.operation, fr.command, stacklevel=2)
    if fr.ok:
        logger.debug(
            "%s ok: %d notes %d accounts %d comments",
            fr.operation,
            len(fr.notes),
            len(fr.accounts),
            len(fr.comments),
            stacklevel=2,
        )
        return
    op = _OP_CN.get(fr.operation, fr.operation)
    kw = f"「{fr.keyword}」" if fr.keyword else ""
    if fr.raw_path:
        # 采集类失败给出详情文件位置（MediaCrawler 子进程完整输出）
        logger.warning(
            "%s%s失败：%s（管线继续）· 采集日志 %s/mediacrawler.log",
            op,
            kw,
            fr.error,
            fr.raw_path,
            stacklevel=2,
        )
    else:
        logger.warning("%s%s失败：%s（管线继续）", op, kw, fr.error, stacklevel=2)
