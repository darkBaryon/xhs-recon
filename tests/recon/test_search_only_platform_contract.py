import pytest

from src.recon.application.search.use_case import SearchContents, SearchRequest
from src.recon.domain.content import Content, Creator, SearchCollectionResult
from src.recon.domain.identity import EntityId, PlatformId
from src.recon.infrastructure.persistence.memory import MemorySearchRepository
from src.recon.platforms.registry import PlatformRegistry

DOUYIN = PlatformId("douyin")


class DouyinSearchOnlyCollector:
    platform_id = "douyin"

    def collect_search(self, request):
        return self.collect_search_batch((request,))[0]

    def collect_search_batch(self, requests):
        return tuple(
            SearchCollectionResult(
                platform=self.platform_id,
                keyword=request.keyword,
                collected_at=request.collected_at,
                creators=(Creator(EntityId(DOUYIN, "creator-1"), nickname="抖音创作者"),),
                contents=(
                    Content(
                        EntityId(DOUYIN, f"content-{request.keyword}"),
                        EntityId(DOUYIN, "creator-1"),
                        title=request.keyword,
                        body="",
                        url="https://www.douyin.com/",
                        published_at=request.collected_at,
                        updated_at=request.collected_at,
                    ),
                ),
            )
            for request in requests
        )


class Output:
    def write(self, analysis):
        return {"report": "douyin-search.md"}


def test_search_only_platform_runs_full_search_without_fake_other_capabilities():
    registry = PlatformRegistry()
    collector = DouyinSearchOnlyCollector()
    registry.register_search_collector(collector)
    repository = MemorySearchRepository()
    use_case = SearchContents(registry.search_collector("douyin"), repository, Output())

    receipt = use_case.execute(
        SearchRequest(
            keywords=("留学辅导",),
            synonyms={"留学辅导": ("essay辅导",)},
            collected_at="2026-07-17T00:00:00+00:00",
        )
    )

    assert receipt.analysis.keywords == ("留学辅导", "essay辅导")
    assert {content.id.platform for content in receipt.analysis.contents} == {DOUYIN}
    assert len(repository.saved) == 2
    with pytest.raises(ValueError, match="does not support creator feeds"):
        registry.creator_feed_collector("douyin")
    with pytest.raises(ValueError, match="does not support content details"):
        registry.content_detail_collector("douyin")
