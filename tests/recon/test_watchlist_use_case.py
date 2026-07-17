from src.recon.application.watchlist.use_case import SyncWatchlist, WatchlistRequest
from src.recon.domain.content import (
    AccountCollectionResult,
    AccountTarget,
    Content,
    ContentReference,
    Creator,
    CreatorFeedResult,
)
from src.recon.domain.identity import EntityId, PlatformId
from src.recon.infrastructure.persistence.memory import MemoryWatchlistRepository

XHS = PlatformId("xhs")


class CreatorFeeds:
    platform_id = "xhs"

    def __init__(self):
        self.calls = []

    def collect_creator_feeds(self, request):
        self.calls.append(request)
        return CreatorFeedResult(
            platform="xhs",
            collected_at=request.collected_at,
            creators=tuple(Creator(target.id) for target in request.targets),
            contents=tuple(
                ContentReference(
                    EntityId(XHS, f"new-{target.id.external_id}"),
                    "url",
                    target.id,
                )
                for target in request.targets
            ),
        )


class ContentDetails:
    platform_id = "xhs"

    def __init__(self):
        self.calls = []

    def collect_content_details(self, request):
        self.calls.append(request)
        return AccountCollectionResult(
            platform="xhs",
            collected_at=request.collected_at,
            contents=tuple(
                Content(
                    id=reference.id,
                    creator_id=reference.creator_id,
                    title="new",
                    body="",
                    url=reference.url,
                    published_at="2026",
                    updated_at="2026",
                )
                for reference in request.contents
            ),
        )


class Output:
    def write(self, analysis):
        return {"report": "watchlist.md"}


def test_watchlist_batches_due_accounts_and_skips_them_until_due_again():
    repository = MemoryWatchlistRepository()
    feeds, details = CreatorFeeds(), ContentDetails()
    use_case = SyncWatchlist(feeds, details, repository, Output())
    request = WatchlistRequest(
        targets=(
            AccountTarget(EntityId(XHS, "account-a")),
            AccountTarget(EntityId(XHS, "account-b")),
        ),
        collected_at="2026-07-16T00:00:00+00:00",
        refresh_days=1,
        fetch_comments=False,
    )

    first = use_case.execute(request)
    second = use_case.execute(request)

    assert len(feeds.calls) == len(details.calls) == 1
    assert len(feeds.calls[0].targets) == 2
    assert len(details.calls[0].contents) == 2
    assert [len(result.contents) for result in first.analysis.collections] == [1, 1]
    assert second.analysis.due == ()
