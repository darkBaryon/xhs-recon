from src.recon.application.account.use_case import AnalyzeAccounts, AnalyzeAccountsRequest
from src.recon.domain.content import (
    AccountCollectionResult,
    AccountTarget,
    Content,
    ContentReference,
    Creator,
    CreatorFeedResult,
    Engagement,
)
from src.recon.domain.identity import EntityId, PlatformId

XHS = PlatformId("xhs")


class CreatorFeeds:
    def __init__(self):
        self.requests = []

    def collect_creator_feeds(self, request):
        self.requests.append(request)
        creator_id = request.targets[0].id
        return CreatorFeedResult(
            platform="xhs",
            collected_at=request.collected_at,
            creators=(Creator(creator_id, nickname="A"),),
            contents=(ContentReference(EntityId(XHS, "n1"), "u", creator_id),),
        )


class ContentDetails:
    def __init__(self):
        self.requests = []

    def collect_content_details(self, request):
        self.requests.append(request)
        creator_id = request.contents[0].creator_id
        return AccountCollectionResult(
            platform="xhs",
            collected_at=request.collected_at,
            contents=(
                Content(
                    id=EntityId(XHS, "n1"),
                    creator_id=creator_id,
                    title="one",
                    body="",
                    url="u",
                    published_at="2026-01-01",
                    updated_at=request.collected_at,
                    engagement=Engagement(likes=10, collects=2, comments=3, shares=1),
                ),
            ),
        )


class Repository:
    def __init__(self):
        self.saved = []

    def save(self, result):
        self.saved.append(result)


class Output:
    def __init__(self):
        self.written = []

    def write(self, analysis):
        self.written.append(analysis)
        return {"report": "report.md"}


def test_account_composes_shared_feed_and_detail_capabilities_once():
    feeds, details, repository, output = CreatorFeeds(), ContentDetails(), Repository(), Output()
    use_case = AnalyzeAccounts(feeds, details, repository, output)
    receipt = use_case.execute(
        AnalyzeAccountsRequest(
            targets=(AccountTarget(EntityId(XHS, "a1")),),
            collected_at="2026",
            fetch_comments=False,
        )
    )

    assert len(feeds.requests) == len(details.requests) == 1
    assert details.requests[0].fetch_comments is False
    assert len(repository.saved) == len(output.written) == 1
    assert receipt.analysis.summaries[0].average_interaction == 16
    assert receipt.output_paths == {"report": "report.md"}


def test_account_with_profile_but_no_posts_still_has_summary():
    creator_id = EntityId(XHS, "empty")
    result = AccountCollectionResult(
        platform="xhs",
        collected_at="2026",
        creators=(Creator(creator_id, nickname="暂无帖子"),),
    )
    from src.recon.domain.policies.aggregate import summarize_accounts

    summary = summarize_accounts(result)[0]
    assert summary.creator_id == creator_id
    assert summary.content_count == 0
    assert summary.average_interaction == 0
