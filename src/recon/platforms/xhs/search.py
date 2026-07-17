from ...application.ports.collection import SearchCollectionRequest
from ...domain.content import (
    CollectionFailure,
    Content,
    Creator,
    Engagement,
    SearchCollectionResult,
)
from ...domain.identity import EntityId
from .collector import XHS
from .contract import XhsAdapter


class XhsSearchCollector:
    platform_id = "xhs"

    def __init__(self, adapter: XhsAdapter) -> None:
        self.adapter = adapter

    def collect_search(self, request: SearchCollectionRequest) -> SearchCollectionResult:
        results = [
            self.adapter.search(request.keyword, page, request.limit, request.collected_at)
            for page in range(1, request.pages + 1)
        ]
        return self._translate(request, results)

    def collect_search_batch(
        self, requests: tuple[SearchCollectionRequest, ...]
    ) -> tuple[SearchCollectionResult, ...]:
        if not requests:
            return ()
        first = requests[0]
        if any(
            request.pages != first.pages
            or request.limit != first.limit
            or request.collected_at != first.collected_at
            for request in requests
        ):
            raise ValueError("同一搜索批次的分页、数量和采集时间必须一致")
        search_many = getattr(self.adapter, "search_many", None)
        if callable(search_many):
            raw_results = search_many(
                [request.keyword for request in requests],
                first.pages,
                first.limit,
                first.collected_at,
            )
        else:
            raw_results = [
                self.adapter.search(request.keyword, page, request.limit, request.collected_at)
                for request in requests
                for page in range(1, request.pages + 1)
            ]
        by_keyword = {request.keyword: [] for request in requests}
        for result in raw_results:
            if result.keyword in by_keyword:
                by_keyword[result.keyword].append(result)
        return tuple(self._translate(request, by_keyword[request.keyword]) for request in requests)

    def _translate(self, request: SearchCollectionRequest, results) -> SearchCollectionResult:
        creators = {}
        contents = {}
        failures = []
        for index, result in enumerate(results, start=1):
            if result.error:
                failures.append(CollectionFailure(str(result.page or index), result.error))
                continue
            for account in result.accounts:
                creator_id = EntityId(XHS, account.account_id)
                creators.setdefault(
                    creator_id,
                    Creator(
                        id=creator_id,
                        nickname=account.nickname,
                        updated_at=request.collected_at,
                    ),
                )
            for note in result.notes:
                content_id = EntityId(XHS, note.note_id)
                creator_id = EntityId(XHS, note.account_id)
                contents.setdefault(
                    content_id,
                    Content(
                        id=content_id,
                        creator_id=creator_id,
                        title=note.title,
                        body=note.body,
                        url=note.url,
                        published_at=note.published_at,
                        updated_at=note.collected_at,
                        engagement=Engagement(
                            likes=note.like_count,
                            collects=note.collect_count,
                            comments=note.comment_count,
                            shares=note.share_count,
                        ),
                        tags=tuple(note.tags),
                        content_type=note.note_type,
                        video_url=note.video_url,
                        image_urls=tuple(note.image_urls),
                        image_paths=tuple(note.image_paths),
                        raw_path=note.raw_path,
                        author_avatar=note.author_avatar,
                        ip_location=note.ip_location,
                    ),
                )
        return SearchCollectionResult(
            platform=self.platform_id,
            keyword=request.keyword,
            collected_at=request.collected_at,
            creators=tuple(creators.values()),
            contents=tuple(contents.values()),
            failures=tuple(failures),
        )
