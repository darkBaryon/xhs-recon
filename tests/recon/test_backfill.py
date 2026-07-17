from src.adapters.fixture_adapter import FixtureAdapter
from src.recon.application.backfill.use_case import BackfillMedia, BackfillRequest
from src.recon.application.ports.collection import ContentDetailCollectionRequest
from src.recon.domain.content import AccountCollectionResult, ContentReference
from src.recon.domain.identity import EntityId, PlatformId
from src.recon.platforms.xhs.details import XhsContentDetailCollector

XHS = PlatformId("xhs")
ACCOUNT = EntityId(XHS, "601d0481000000000101cc46")
NOTE = EntityId(XHS, "6a4661cd0000000017029d86")
URL = "https://www.xiaohongshu.com/explore/6a4661cd0000000017029d86?xsec_token=t"


class Repository:
    def __init__(self):
        self.saved = []

    def contents_missing_media(self, limit):
        return (ContentReference(NOTE, URL, ACCOUNT),)

    def save_backfill(self, result):
        self.saved.append(result)


class Collector:
    platform_id = "xhs"

    def collect_content_details(self, request):
        return AccountCollectionResult(platform="xhs", collected_at=request.collected_at)


def test_backfill_application_is_independent_from_search_and_watchlist():
    repository = Repository()
    receipt = BackfillMedia(Collector(), repository).execute(BackfillRequest("2026", batch_size=1))
    assert receipt.requested == 1
    assert len(repository.saved) == 1


def test_xhs_content_detail_collector_translates_fixture_details():
    adapter = FixtureAdapter(
        "tests/fixtures/search_contents_sample.jsonl",
        creator_path="tests/fixtures/creator_contents_sample.jsonl",
    )
    result = XhsContentDetailCollector(adapter).collect_content_details(
        ContentDetailCollectionRequest(
            contents=(ContentReference(NOTE, URL, ACCOUNT),),
            collected_at="2026",
        )
    )
    assert [content.id for content in result.contents] == [NOTE]
    assert result.contents[0].creator_id == ACCOUNT
