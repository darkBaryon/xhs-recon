from contextlib import contextmanager

from src.recon.application.ports.collection import (
    ContentDetailCollectionRequest,
    SearchCollectionRequest,
)
from src.recon.domain.content import (
    AccountCollectionResult,
    ContentReference,
    SearchCollectionResult,
)
from src.recon.domain.identity import EntityId, PlatformId
from src.recon.entrypoints import progress as progress_module

XHS = PlatformId("xhs")


class Adapter:
    on_progress = None


class ContentDetailCollector:
    platform_id = "xhs"

    def __init__(self, adapter):
        self.adapter = adapter

    def collect_content_details(self, request):
        self.adapter.on_progress({"kind": "note", "count": 1})
        return AccountCollectionResult(platform="xhs", collected_at=request.collected_at)


class SearchCollector:
    platform_id = "xhs"

    def __init__(self, adapter):
        self.adapter = adapter

    def collect_search_batch(self, requests):
        self.adapter.on_progress({"kind": "keyword_start", "index": 1, "keyword": "k"})
        return tuple(
            SearchCollectionResult(
                platform="xhs", keyword=request.keyword, collected_at=request.collected_at
            )
            for request in requests
        )


def _progress_capture(events):
    @contextmanager
    def capture(*args, **kwargs):
        events.append((args, kwargs))
        yield events.append

    return capture


def test_content_detail_progress_is_an_entrypoint_decorator(monkeypatch):
    adapter = Adapter()
    events = []
    monkeypatch.setattr(progress_module.progress, "detail_progress", _progress_capture(events))
    collector = progress_module.ProgressContentDetailCollector(
        ContentDetailCollector(adapter), adapter
    )

    collector.collect_content_details(
        ContentDetailCollectionRequest(
            contents=(
                ContentReference(
                    EntityId(XHS, "n1"),
                    "url",
                    EntityId(XHS, "a1"),
                ),
            ),
            collected_at="2026",
        )
    )

    assert {event["kind"] for event in events if isinstance(event, dict)} == {"note"}
    assert adapter.on_progress is None


def test_search_progress_is_an_entrypoint_decorator(monkeypatch):
    adapter = Adapter()
    events = []
    monkeypatch.setattr(progress_module.progress, "search_progress", _progress_capture(events))
    collector = progress_module.ProgressSearchCollector(SearchCollector(adapter), adapter)

    collector.collect_search_batch((SearchCollectionRequest(keyword="k", collected_at="2026"),))

    assert {event["kind"] for event in events if isinstance(event, dict)} == {
        "keyword_start",
        "done",
    }
    assert adapter.on_progress is None
