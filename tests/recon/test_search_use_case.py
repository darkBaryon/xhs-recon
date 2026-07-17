from src.recon.application.search.use_case import SearchContents, SearchRequest
from src.recon.domain.content import (
    CollectionFailure,
    Content,
    Creator,
    Engagement,
    SearchCollectionResult,
)
from src.recon.domain.identity import EntityId, PlatformId

XHS = PlatformId("xhs")


class Collector:
    platform_id = "xhs"

    def collect_search(self, request):
        creator_id = EntityId(XHS, "creator")
        return SearchCollectionResult(
            platform="xhs",
            keyword=request.keyword,
            collected_at=request.collected_at,
            creators=(Creator(creator_id, nickname="账号"),),
            contents=(
                Content(
                    id=EntityId(XHS, "same-content"),
                    creator_id=creator_id,
                    title=request.keyword,
                    body="",
                    url="url",
                    published_at="2026-07-15T00:00:00+00:00",
                    updated_at=request.collected_at,
                    engagement=Engagement(likes=10),
                ),
            ),
        )

    def collect_search_batch(self, requests):
        return tuple(self.collect_search(request) for request in requests)


class Repository:
    def __init__(self):
        self.saved = []

    def save_search(self, result):
        self.saved.append(result)


class Output:
    def write(self, analysis):
        return {"report": "search.md"}


def test_search_is_independent_and_preserves_cross_keyword_ownership():
    repository = Repository()
    receipt = SearchContents(Collector(), repository, Output()).execute(
        SearchRequest(
            keywords=("留学辅导",),
            synonyms={"留学辅导": ("essay辅导",)},
            collected_at="2026-07-16T00:00:00+00:00",
        )
    )

    assert [result.keyword for result in repository.saved] == ["留学辅导", "essay辅导"]
    assert len(receipt.analysis.contents) == 1
    assert receipt.analysis.ranks[0].keyword_count == 2
    assert receipt.output_paths == {"report": "search.md"}


def test_search_stops_future_batches_after_risk_signal():
    class RiskCollector(Collector):
        def __init__(self):
            self.batches = []

        def collect_search_batch(self, requests):
            self.batches.append(tuple(request.keyword for request in requests))
            request = requests[0]
            return (
                SearchCollectionResult(
                    platform="xhs",
                    keyword=request.keyword,
                    collected_at=request.collected_at,
                    failures=(
                        CollectionFailure(request.keyword, "检测到平台风险信号，采集已熔断"),
                    ),
                ),
            )

    collector = RiskCollector()
    repository = Repository()
    SearchContents(collector, repository, Output()).execute(
        SearchRequest(
            keywords=("AP课程", "AP备考", "A-Level课程"),
            collected_at="2026",
            batch_size=1,
        )
    )

    assert collector.batches == [("AP课程",)]
