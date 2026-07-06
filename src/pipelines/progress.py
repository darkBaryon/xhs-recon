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
    # 保留完成态：后一个任务新开一行，不覆盖前一个任务；结束后也留在终端历史里。
    return Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


def _default_console() -> Console:
    return Console(stderr=True)


def _can_render(console: Console) -> bool:
    return console.is_terminal and not console.is_dumb_terminal


@contextmanager
def stage_bar(description: str, total: int, console: Console | None = None) -> Iterator[_NullBar]:
    """单任务进度条（搜索段用）：yield 一个 describe()/advance() 句柄。

    非 TTY 或 total<=0 时 yield 空实现。console 参数仅供测试注入。
    """
    console = console or _default_console()
    if not _can_render(console) or total <= 0:
        yield _NullBar()
        return
    with _make_progress(console) as progress:
        task_id = progress.add_task(description, total=total)
        yield _RichBar(progress, task_id)


@contextmanager
def creator_progress(
    total: int,
    names: dict[str, str] | None = None,
    notes_per_creator: int | None = None,
    console: Console | None = None,
) -> Iterator[ProgressCallback | None]:
    """creator 单会话进度：yield 一个 adapter 进度事件回调（非 TTY 时 yield None）。

    事件约定（与 MediaCrawlerAdapter 的 emit 对应）：
      {"kind": "creator_start", "index": k, "user_id": id} → 第 k 个账号开始
      {"kind": "note", "count": m} → 当前账号拉到一条笔记（count 仅作兼容信息）
    names：account_id → 显示名（如 watchlist 昵称），缺省显示 user_id。
    """
    console = console or _default_console()
    if not _can_render(console) or total <= 0:
        yield None
        return
    with _make_progress(console) as progress:
        task_id = progress.add_task("创作者", total=total)
        note_task_id = None
        state = {"label": "", "notes": 0}

        def on_progress(event: dict) -> None:
            nonlocal note_task_id
            kind = event.get("kind")
            if kind == "creator_start":
                index = event.get("index", 1)
                user_id = event.get("user_id", "")
                state["label"] = (names or {}).get(user_id) or user_id
                state["notes"] = 0
                # 第 k 个开始 = 前 k-1 个已完成
                progress.update(
                    task_id,
                    completed=max(index - 1, 0),
                    description=f"创作者 {state['label']}",
                    refresh=True,
                )
                note_task_id = progress.add_task(
                    f"{state['label']} 笔记 0",
                    total=notes_per_creator,
                )
            elif kind == "note":
                if note_task_id is None:
                    note_task_id = progress.add_task("笔记 0", total=notes_per_creator)
                state["notes"] = state["notes"] + 1
                progress.update(
                    note_task_id,
                    advance=1,
                    description=f"{state['label']} 笔记 {state['notes']}",
                    refresh=True,
                )
            elif kind == "done":
                progress.update(task_id, completed=total, refresh=True)

        yield on_progress


@contextmanager
def search_progress(
    total: int, notes_per_keyword: int | None = None, console: Console | None = None
) -> Iterator[ProgressCallback | None]:
    """search 单会话进度：父任务显示关键词序号，子任务显示当前关键词详情请求。"""
    console = console or _default_console()
    if not _can_render(console) or total <= 0:
        yield None
        return
    with _make_progress(console) as rich_progress:
        keyword_task_id = rich_progress.add_task("搜索关键词", total=total)
        note_task_id = None
        state = {"keyword": "", "notes": 0}

        def on_progress(event: dict) -> None:
            nonlocal note_task_id
            kind = event.get("kind")
            if kind == "keyword_start":
                index = event.get("index", 1)
                state["keyword"] = event.get("keyword", "")
                state["notes"] = 0
                rich_progress.update(
                    keyword_task_id,
                    completed=max(index - 1, 0),
                    description=f"搜索「{state['keyword']}」",
                    refresh=True,
                )
                note_task_id = rich_progress.add_task(
                    f"{state['keyword']} 详情 0",
                    total=notes_per_keyword,
                )
            elif kind == "page_start":
                keyword = event.get("keyword") or state["keyword"]
                page = event.get("page")
                rich_progress.update(
                    keyword_task_id,
                    description=f"搜索「{keyword}」第 {page} 页",
                    refresh=True,
                )
            elif kind == "note":
                if note_task_id is None:
                    note_task_id = rich_progress.add_task("详情 0", total=notes_per_keyword)
                state["notes"] = state["notes"] + 1
                rich_progress.update(
                    note_task_id,
                    advance=1,
                    description=f"{state['keyword']} 详情 {state['notes']}",
                    refresh=True,
                )
            elif kind == "done":
                rich_progress.update(keyword_task_id, completed=total, refresh=True)

        yield on_progress


@contextmanager
def detail_progress(
    total: int, console: Console | None = None
) -> Iterator[ProgressCallback | None]:
    """两段式详情段进度：yield adapter 进度事件回调（非 TTY 时 None）。

    MC detail 会话分两个阶段：正文/图并发抓（note 事件几秒内全到）、评论串行
    限速抓（comments 事件才是真实节奏）——各画一条，避免单条秒满后挂满格。
    """
    console = console or _default_console()
    if not _can_render(console) or total <= 0:
        yield None
        return
    with _make_progress(console) as progress:
        note_task_id = progress.add_task("新帖正文/图", total=total)
        comments_task_id = progress.add_task("新帖评论", total=total)
        state = {"note": 0, "comments": 0}

        def on_progress(event: dict) -> None:
            kind = event.get("kind")
            if kind == "note":
                state["note"] += 1
                progress.update(note_task_id, completed=state["note"], refresh=True)
            elif kind == "comments":
                state["comments"] += 1
                progress.update(comments_task_id, completed=state["comments"], refresh=True)

        yield on_progress


@contextmanager
def spinner(description: str, console: Console | None = None) -> Iterator[None]:
    """无进度语义的长等待（评论段用）：转圈提示。非 TTY 时无输出。"""
    console = console or _default_console()
    if not _can_render(console):
        yield
        return
    with console.status(description):
        yield
