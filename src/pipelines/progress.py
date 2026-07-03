"""终端进度显示（rich）：只在 TTY 画、走 stderr，绝不进 data/logs 或导出文件。

分层口径：本模块是 pipelines 私有的显示层。adapter 只 emit 语义事件
（dict，如 {"kind": "creator_start", ...}），由这里翻译成进度条；
rich 不得漏进 core/adapters。

非 TTY（测试/管道/重定向）时所有入口退化为 no-op，不产生任何输出。
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

# adapter 进度事件（dict）的消费端类型；与 adapter 侧的 emit 约定对应
ProgressCallback = Callable[[dict], None]


class _NullBar:
    """非 TTY 时的空实现：调用零副作用。"""

    def describe(self, text: str) -> None:
        pass

    def advance(self, n: int = 1) -> None:
        pass


class _RichBar:
    def __init__(self, progress: Progress, task_id) -> None:
        self._progress = progress
        self._task_id = task_id

    # refresh=True：事件频率低（每词/每笔记一次），即时重绘代价可忽略，
    # 且不依赖 rich 的 10Hz 定时线程（短周期内可能一次都不触发）
    def describe(self, text: str) -> None:
        self._progress.update(self._task_id, description=text, refresh=True)

    def advance(self, n: int = 1) -> None:
        self._progress.update(self._task_id, advance=n, refresh=True)


def _make_progress(console: Console) -> Progress:
    # transient：跑完消失，不在滚动历史里留残条（历史叙事归 logging）
    return Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )


def _default_console() -> Console:
    return Console(stderr=True)


@contextmanager
def stage_bar(description: str, total: int, console: Console | None = None) -> Iterator[_NullBar]:
    """单任务进度条（搜索段用）：yield 一个 describe()/advance() 句柄。

    非 TTY 或 total<=0 时 yield 空实现。console 参数仅供测试注入。
    """
    console = console or _default_console()
    if not console.is_terminal or total <= 0:
        yield _NullBar()
        return
    with _make_progress(console) as progress:
        task_id = progress.add_task(description, total=total)
        yield _RichBar(progress, task_id)


@contextmanager
def creator_progress(
    total: int, names: dict[str, str] | None = None, console: Console | None = None
) -> Iterator[ProgressCallback | None]:
    """creator 单会话进度：yield 一个 adapter 进度事件回调（非 TTY 时 yield None）。

    事件约定（与 MediaCrawlerAdapter 的 emit 对应）：
      {"kind": "creator_start", "index": k, "user_id": id} → 第 k 个账号开始
      {"kind": "note", "count": m} → 会话累计拉到第 m 条笔记
    names：account_id → 显示名（如 watchlist 昵称），缺省显示 user_id。
    """
    console = console or _default_console()
    if not console.is_terminal or total <= 0:
        yield None
        return
    with _make_progress(console) as progress:
        task_id = progress.add_task("创作者", total=total)
        state = {"label": "", "notes": 0}

        def on_progress(event: dict) -> None:
            kind = event.get("kind")
            if kind == "creator_start":
                index = event.get("index", 1)
                user_id = event.get("user_id", "")
                state["label"] = (names or {}).get(user_id) or user_id
                # 第 k 个开始 = 前 k-1 个已完成
                progress.update(
                    task_id,
                    completed=max(index - 1, 0),
                    description=f"创作者 {state['label']}",
                    refresh=True,
                )
            elif kind == "note":
                state["notes"] = event.get("count", state["notes"] + 1)
                progress.update(
                    task_id,
                    description=f"创作者 {state['label']} · 笔记 {state['notes']}",
                    refresh=True,
                )

        yield on_progress


@contextmanager
def spinner(description: str, console: Console | None = None) -> Iterator[None]:
    """无进度语义的长等待（评论段用）：转圈提示。非 TTY 时无输出。"""
    console = console or _default_console()
    if not console.is_terminal:
        yield
        return
    with console.status(description):
        yield
