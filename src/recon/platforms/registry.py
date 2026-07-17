from ..application.ports.collection import (
    ContentDetailCollector,
    CreatorFeedCollector,
    SearchCollector,
)


class PlatformRegistry:
    def __init__(self) -> None:
        self._search_collectors: dict[str, SearchCollector] = {}
        self._creator_feed_collectors: dict[str, CreatorFeedCollector] = {}
        self._content_detail_collectors: dict[str, ContentDetailCollector] = {}

    def register_search_collector(self, collector: SearchCollector) -> None:
        if collector.platform_id in self._search_collectors:
            raise ValueError(f"duplicate search platform: {collector.platform_id}")
        self._search_collectors[collector.platform_id] = collector

    def search_collector(self, platform_id: str) -> SearchCollector:
        try:
            return self._search_collectors[platform_id]
        except KeyError as exc:
            message = f"platform {platform_id!r} does not support search"
            raise ValueError(message) from exc

    def register_creator_feed_collector(self, collector: CreatorFeedCollector) -> None:
        if collector.platform_id in self._creator_feed_collectors:
            raise ValueError(f"duplicate creator feed platform: {collector.platform_id}")
        self._creator_feed_collectors[collector.platform_id] = collector

    def creator_feed_collector(self, platform_id: str) -> CreatorFeedCollector:
        try:
            return self._creator_feed_collectors[platform_id]
        except KeyError as exc:
            message = f"platform {platform_id!r} does not support creator feeds"
            raise ValueError(message) from exc

    def register_content_detail_collector(self, collector: ContentDetailCollector) -> None:
        if collector.platform_id in self._content_detail_collectors:
            raise ValueError(f"duplicate content detail platform: {collector.platform_id}")
        self._content_detail_collectors[collector.platform_id] = collector

    def content_detail_collector(self, platform_id: str) -> ContentDetailCollector:
        try:
            return self._content_detail_collectors[platform_id]
        except KeyError as exc:
            message = f"platform {platform_id!r} does not support content details"
            raise ValueError(message) from exc
