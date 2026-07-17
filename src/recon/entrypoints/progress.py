from contextlib import contextmanager

from ..application.ports.collection import (
    ContentDetailCollectionRequest,
    ContentDetailCollector,
    CreatorFeedCollectionRequest,
    CreatorFeedCollector,
    SearchCollectionRequest,
    SearchCollector,
)
from ..domain.content import AccountCollectionResult, CreatorFeedResult, SearchCollectionResult
from . import progress_ui as progress


@contextmanager
def _bind_adapter(adapter, callback):
    existed = hasattr(adapter, "on_progress")
    previous = getattr(adapter, "on_progress", None)
    adapter.on_progress = callback
    try:
        yield
    finally:
        if existed:
            adapter.on_progress = previous
        else:
            del adapter.on_progress


class ProgressSearchCollector:
    """为 search 能力增加 TTY 进度条；非 TTY 自动退化为空操作。"""

    def __init__(self, inner: SearchCollector, adapter) -> None:
        self.inner = inner
        self.adapter = adapter
        self.platform_id = inner.platform_id

    def collect_search(self, request: SearchCollectionRequest) -> SearchCollectionResult:
        return self.collect_search_batch((request,))[0]

    def collect_search_batch(
        self, requests: tuple[SearchCollectionRequest, ...]
    ) -> tuple[SearchCollectionResult, ...]:
        if not requests:
            return ()
        notes_per_keyword = max(requests[0].pages, 1) * max(requests[0].limit, 1)
        with progress.search_progress(len(requests), notes_per_keyword) as callback:
            with _bind_adapter(self.adapter, callback):
                results = self.inner.collect_search_batch(requests)
            if callback is not None:
                callback({"kind": "done"})
            return results


class ProgressCreatorFeedCollector:
    """一批账号共用一个列表会话，显示层不改变批量语义。"""

    def __init__(self, inner: CreatorFeedCollector) -> None:
        self.inner = inner
        self.platform_id = inner.platform_id

    def collect_creator_feeds(self, request: CreatorFeedCollectionRequest) -> CreatorFeedResult:
        with progress.spinner(f"批量检查 {len(request.targets)} 个账号主页…"):
            return self.inner.collect_creator_feeds(request)


class ProgressContentDetailCollector:
    def __init__(self, inner: ContentDetailCollector, adapter) -> None:
        self.inner = inner
        self.adapter = adapter
        self.platform_id = inner.platform_id

    def collect_content_details(
        self, request: ContentDetailCollectionRequest
    ) -> AccountCollectionResult:
        with progress.detail_progress(len(request.contents)) as callback:
            with _bind_adapter(self.adapter, callback):
                return self.inner.collect_content_details(request)
