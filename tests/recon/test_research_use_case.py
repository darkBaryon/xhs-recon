from src.recon.application.research.use_case import ResearchRequest, RunResearch
from src.recon.application.search.use_case import SearchRequest
from src.recon.domain.content import AccountTarget
from src.recon.domain.identity import EntityId, PlatformId
from src.recon.domain.research import (
    CreatorRank,
    SearchAnalysis,
    SearchReceipt,
    WatchlistAnalysis,
    WatchlistReceipt,
)

XHS = PlatformId("xhs")


class Search:
    def execute(self, request):
        rank = CreatorRank(EntityId(XHS, "auto"), "自动账号", 2, 1, 10, 20)
        return SearchReceipt(SearchAnalysis(("k",), (), (), (), (rank,)), {})


class Watchlist:
    request = None

    def execute(self, request):
        self.request = request
        analysis = WatchlistAnalysis(request.targets, (), ())
        return WatchlistReceipt(analysis, {})


class Bundle:
    def write(self, analysis):
        return {"bundle": "research.zip"}


def test_research_composes_auto_targets_without_coupling_child_services():
    watchlist = Watchlist()
    service = RunResearch(Search(), watchlist, Bundle())
    receipt = service.execute(
        ResearchRequest(
            search=SearchRequest(("k",), "2026"),
            manual_targets=(AccountTarget(EntityId(XHS, "manual")),),
            auto_top_n=1,
            max_total=2,
        )
    )

    assert [target.id.external_id for target in watchlist.request.targets] == [
        "manual",
        "auto",
    ]
    assert watchlist.request.targets[1].source == "auto"
    assert receipt.output_paths == {"bundle": "research.zip"}
