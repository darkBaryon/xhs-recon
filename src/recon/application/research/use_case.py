import logging
from dataclasses import dataclass

from ...domain.content import AccountTarget
from ...domain.research import ResearchAnalysis, ResearchReceipt
from ..ports.output import ResearchBundleOutput
from ..search.use_case import SearchContents, SearchRequest
from ..watchlist.use_case import SyncWatchlist, WatchlistRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResearchRequest:
    search: SearchRequest
    manual_targets: tuple[AccountTarget, ...]
    auto_top_n: int = 0
    max_total: int = 10
    watchlist_max_notes: int = 10
    watchlist_batch_size: int = 0
    watchlist_refresh_days: int = 0
    watchlist_comments_refresh_days: int = 0
    fetch_comments: bool = True


class RunResearch:
    """组合独立服务；search/watchlist 自身不知道彼此存在。"""

    def __init__(
        self,
        search: SearchContents,
        watchlist: SyncWatchlist,
        bundle: ResearchBundleOutput,
    ) -> None:
        self.search = search
        self.watchlist = watchlist
        self.bundle = bundle

    def execute(self, request: ResearchRequest) -> ResearchReceipt:
        logger.info("组合研究开始：先搜索，再组装本次 watchlist")
        search_receipt = self.search.execute(request.search)
        targets = list(request.manual_targets)
        existing = {target.id for target in targets}
        auto_count = 0
        for rank in search_receipt.analysis.ranks:
            if auto_count >= request.auto_top_n:
                break
            if rank.creator_id in existing:
                continue
            if request.max_total > 0 and len(targets) >= request.max_total:
                break
            targets.append(AccountTarget(rank.creator_id, rank.nickname, "auto"))
            existing.add(rank.creator_id)
            auto_count += 1
        watchlist_receipt = self.watchlist.execute(
            WatchlistRequest(
                targets=tuple(targets),
                collected_at=request.search.collected_at,
                max_notes=request.watchlist_max_notes,
                batch_size=request.watchlist_batch_size,
                refresh_days=request.watchlist_refresh_days,
                comments_refresh_days=request.watchlist_comments_refresh_days,
                fetch_comments=request.fetch_comments,
            )
        )
        analysis = ResearchAnalysis(
            search=search_receipt.analysis,
            watchlist=watchlist_receipt.analysis,
            manual_count=len(request.manual_targets),
            auto_count=auto_count,
        )
        paths = {
            **{f"search_{key}": value for key, value in search_receipt.output_paths.items()},
            **{f"watchlist_{key}": value for key, value in watchlist_receipt.output_paths.items()},
            **self.bundle.write(analysis),
        }
        logger.info("组合研究完成：manual %d · auto %d", len(request.manual_targets), auto_count)
        return ResearchReceipt(analysis=analysis, output_paths=paths)
