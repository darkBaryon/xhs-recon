from src.adapters.fixture_adapter import FixtureAdapter
from src.recon.application.watchlist.use_case import SyncWatchlist, WatchlistRequest
from src.recon.domain.content import AccountTarget
from src.recon.platforms.xhs.collector import XhsCreatorFeedCollector, normalize_xhs_target
from src.recon.platforms.xhs.details import XhsContentDetailCollector

ACCOUNT = "601d0481000000000101cc46"
MISSING = "aaaaaaaaaaaaaaaaaaaaaaaa"


class RecordingFixtureAdapter(FixtureAdapter):
    def __init__(self):
        super().__init__(
            "tests/fixtures/search_contents_sample.jsonl",
            creator_path="tests/fixtures/creator_contents_sample.jsonl",
            creator_profiles_path="tests/fixtures/creator_creators_sample.jsonl",
        )
        self.list_calls = []
        self.detail_calls = []

    def list_creator_notes(self, account_ids, collected_at, limit=None):
        self.list_calls.append((tuple(account_ids), limit))
        return super().list_creator_notes(account_ids, collected_at, limit)

    def fetch_note_details(self, cards, collected_at, with_comments=True):
        self.detail_calls.append(tuple(card["note_id"] for card in cards))
        return super().fetch_note_details(cards, collected_at, with_comments)


class Repository:
    def __init__(self):
        self.saved = []

    def due_targets(self, targets, *args):
        return targets

    def known_content_ids(self, target):
        return frozenset()

    def content_ids_needing_comments(self, *args):
        return frozenset()

    def save_watchlist(self, result, *, comments_fetched):
        self.saved.append(result)


class Output:
    def write(self, analysis):
        return {}


def test_xhs_watchlist_uses_one_list_and_one_detail_session_for_batch():
    adapter = RecordingFixtureAdapter()
    repository = Repository()
    service = SyncWatchlist(
        XhsCreatorFeedCollector(adapter),
        XhsContentDetailCollector(adapter),
        repository,
        Output(),
    )
    receipt = service.execute(
        WatchlistRequest(
            targets=(
                AccountTarget(normalize_xhs_target(ACCOUNT)),
                AccountTarget(normalize_xhs_target(MISSING)),
            ),
            collected_at="2026",
            max_notes=10,
            fetch_comments=False,
        )
    )

    assert adapter.list_calls == [((ACCOUNT, MISSING), 10)]
    assert len(adapter.detail_calls) == 1
    assert len(adapter.detail_calls[0]) == 2
    assert len(repository.saved) == 2
    assert receipt.analysis.collections[0].failures == ()
    assert receipt.analysis.collections[1].failures[0].target_external_id == MISSING
