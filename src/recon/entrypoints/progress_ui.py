"""新入口的 TTY 进度显示；非 TTY 自动静默。"""

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

ProgressCallback = Callable[[dict], None]


def _make_progress(console: Console) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


def _console(value: Console | None) -> Console:
    return value or Console(stderr=True)


def _can_render(console: Console) -> bool:
    return console.is_terminal and not console.is_dumb_terminal


@contextmanager
def creator_progress(
    total: int,
    names: dict[str, str] | None = None,
    notes_per_creator: int | None = None,
    console: Console | None = None,
) -> Iterator[ProgressCallback | None]:
    console = _console(console)
    if not _can_render(console) or total <= 0:
        yield None
        return
    with _make_progress(console) as progress:
        creator_task = progress.add_task("创作者", total=total)
        note_task = None
        state = {"label": "", "notes": 0}

        def update(event: dict) -> None:
            nonlocal note_task
            kind = event.get("kind")
            if kind == "creator_start":
                index = event.get("index", 1)
                user_id = event.get("user_id", "")
                state["label"] = (names or {}).get(user_id) or user_id
                state["notes"] = 0
                progress.update(
                    creator_task,
                    completed=max(index - 1, 0),
                    description=f"创作者 {state['label']}",
                    refresh=True,
                )
                note_task = progress.add_task(f"{state['label']} 笔记 0", total=notes_per_creator)
            elif kind == "note":
                if note_task is None:
                    note_task = progress.add_task("笔记 0", total=notes_per_creator)
                state["notes"] += 1
                progress.update(
                    note_task,
                    advance=1,
                    description=f"{state['label']} 笔记 {state['notes']}",
                    refresh=True,
                )
            elif kind == "done":
                progress.update(creator_task, completed=total, refresh=True)

        yield update


@contextmanager
def search_progress(
    total: int,
    notes_per_keyword: int | None = None,
    console: Console | None = None,
) -> Iterator[ProgressCallback | None]:
    console = _console(console)
    if not _can_render(console) or total <= 0:
        yield None
        return
    with _make_progress(console) as progress:
        keyword_task = progress.add_task("搜索关键词", total=total)
        note_task = None
        state = {"keyword": "", "notes": 0}

        def update(event: dict) -> None:
            nonlocal note_task
            kind = event.get("kind")
            if kind == "keyword_start":
                index = event.get("index", 1)
                state["keyword"] = event.get("keyword", "")
                state["notes"] = 0
                progress.update(
                    keyword_task,
                    completed=max(index - 1, 0),
                    description=f"搜索「{state['keyword']}」",
                    refresh=True,
                )
                note_task = progress.add_task(f"{state['keyword']} 详情 0", total=notes_per_keyword)
            elif kind == "page_start":
                keyword = event.get("keyword") or state["keyword"]
                progress.update(
                    keyword_task,
                    description=f"搜索「{keyword}」第 {event.get('page')} 页",
                    refresh=True,
                )
            elif kind == "note":
                if note_task is None:
                    note_task = progress.add_task("详情 0", total=notes_per_keyword)
                state["notes"] += 1
                progress.update(
                    note_task,
                    advance=1,
                    description=f"{state['keyword']} 详情 {state['notes']}",
                    refresh=True,
                )
            elif kind == "done":
                progress.update(keyword_task, completed=total, refresh=True)

        yield update


@contextmanager
def detail_progress(
    total: int, console: Console | None = None
) -> Iterator[ProgressCallback | None]:
    console = _console(console)
    if not _can_render(console) or total <= 0:
        yield None
        return
    with _make_progress(console) as progress:
        note_task = progress.add_task("新帖正文/图", total=total)
        comments_task = progress.add_task("新帖评论·已收    0 条", total=total)
        state = {"note": 0, "comments": 0, "comment_rows": 0}

        def update(event: dict) -> None:
            kind = event.get("kind")
            if kind == "note":
                state["note"] += 1
                progress.update(note_task, completed=state["note"], refresh=True)
            elif kind == "comments":
                state["comments"] += 1
                progress.update(comments_task, completed=state["comments"], refresh=True)
            elif kind == "comment_rows":
                state["comment_rows"] = event.get("count", state["comment_rows"] + 1)
                progress.update(
                    comments_task,
                    description=f"新帖评论·已收 {state['comment_rows']:>4} 条",
                )

        yield update


@contextmanager
def spinner(description: str, console: Console | None = None) -> Iterator[None]:
    console = _console(console)
    if not _can_render(console):
        yield
        return
    with console.status(description):
        yield
