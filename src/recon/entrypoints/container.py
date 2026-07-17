from pathlib import Path

from ..application.account.use_case import AnalyzeAccounts
from ..application.backfill.use_case import BackfillMedia
from ..application.research.use_case import RunResearch
from ..application.search.use_case import SearchContents
from ..application.watchlist.use_case import SyncWatchlist
from ..infrastructure.output.account_files import AccountFilesOutput
from ..infrastructure.output.bundle import ResearchBundleFilesOutput
from ..infrastructure.output.search_files import SearchFilesOutput
from ..infrastructure.output.watchlist_files import WatchlistFilesOutput
from ..infrastructure.persistence.memory import (
    MemoryAccountRepository,
    MemorySearchRepository,
    MemoryWatchlistRepository,
)
from ..infrastructure.persistence.mysql.repository import MySQLResearchRepository
from ..platforms.registry import PlatformRegistry
from ..platforms.xhs.collector import XhsCreatorFeedCollector
from ..platforms.xhs.details import XhsContentDetailCollector
from ..platforms.xhs.search import XhsSearchCollector
from . import runtime
from .config import LoadedAccountConfig, LoadedSearchConfig, LoadedWatchlistConfig
from .logging_setup import configure_logging
from .progress import (
    ProgressContentDetailCollector,
    ProgressCreatorFeedCollector,
    ProgressSearchCollector,
)


def build_account_use_case(config: LoadedAccountConfig, collected_at: str, *, verbose: bool):
    run = config.run
    account_cfg = run.account_analysis
    assert account_cfg is not None
    if run.provider == "mediacrawler":
        if not run.mediacrawler_dir or not Path(run.mediacrawler_dir).exists():
            raise ValueError(f"MediaCrawler 目录不可用：{run.mediacrawler_dir or '<empty>'}")
    if account_cfg.download_images is not None:
        run = run.model_copy(
            update={
                "mediacrawler": run.mediacrawler.model_copy(
                    update={"download_images": account_cfg.download_images}
                )
            }
        )
    adapter = runtime.build_adapter(run)
    configure_logging(
        run.logging.model_dump(),
        verbose=verbose,
        run_id=collected_at,
        provider=adapter.provider_name,
    )
    creator_feeds = ProgressCreatorFeedCollector(XhsCreatorFeedCollector(adapter))
    content_details = ProgressContentDetailCollector(XhsContentDetailCollector(adapter), adapter)
    registry = PlatformRegistry()
    registry.register_creator_feed_collector(creator_feeds)
    registry.register_content_detail_collector(content_details)
    repository = (
        MySQLResearchRepository(run.store.database)
        if run.store.enabled
        else MemoryAccountRepository()
    )
    run_name = runtime.compact_run_id(collected_at) + "-account"
    output = AccountFilesOutput(Path(run.export.out_dir), run_name)
    return (
        AnalyzeAccounts(
            registry.creator_feed_collector("xhs"),
            registry.content_detail_collector("xhs"),
            repository,
            output,
        ),
        repository,
    )


def build_search_use_case(config: LoadedSearchConfig, collected_at: str, *, verbose: bool):
    run = config.run
    if run.provider == "mediacrawler":
        if not run.mediacrawler_dir or not Path(run.mediacrawler_dir).exists():
            raise ValueError(f"MediaCrawler 目录不可用：{run.mediacrawler_dir or '<empty>'}")
    adapter = runtime.build_adapter(run)
    configure_logging(
        run.logging.model_dump(),
        verbose=verbose,
        run_id=collected_at,
        provider=adapter.provider_name,
    )
    collector = ProgressSearchCollector(XhsSearchCollector(adapter), adapter)
    registry = PlatformRegistry()
    registry.register_search_collector(collector)
    repository = (
        MySQLResearchRepository(run.store.database)
        if run.store.enabled
        else MemorySearchRepository()
    )
    run_name = runtime.compact_run_id(collected_at) + "-search"
    output = SearchFilesOutput(Path(run.export.out_dir), run_name)
    return (
        SearchContents(
            registry.search_collector("xhs"),
            repository,
            output,
            runtime.SystemSleeper(),
        ),
        repository,
    )


def build_watchlist_use_case(config: LoadedWatchlistConfig, collected_at: str, *, verbose: bool):
    run = config.run
    if run.provider == "mediacrawler":
        if not run.mediacrawler_dir or not Path(run.mediacrawler_dir).exists():
            raise ValueError(f"MediaCrawler 目录不可用：{run.mediacrawler_dir or '<empty>'}")
    adapter = runtime.build_adapter(run)
    configure_logging(
        run.logging.model_dump(),
        verbose=verbose,
        run_id=collected_at,
        provider=adapter.provider_name,
    )
    creator_feeds = ProgressCreatorFeedCollector(XhsCreatorFeedCollector(adapter))
    content_details = ProgressContentDetailCollector(XhsContentDetailCollector(adapter), adapter)
    registry = PlatformRegistry()
    registry.register_creator_feed_collector(creator_feeds)
    registry.register_content_detail_collector(content_details)
    repository = (
        MySQLResearchRepository(run.store.database)
        if run.store.enabled
        else MemoryWatchlistRepository()
    )
    run_name = runtime.compact_run_id(collected_at) + "-watchlist"
    output = WatchlistFilesOutput(Path(run.export.out_dir), run_name)
    return (
        SyncWatchlist(
            registry.creator_feed_collector("xhs"),
            registry.content_detail_collector("xhs"),
            repository,
            output,
        ),
        repository,
    )


def build_research_use_case(
    search_config: LoadedSearchConfig,
    watchlist_config: LoadedWatchlistConfig,
    collected_at: str,
    *,
    verbose: bool,
):
    search, search_repository = build_search_use_case(search_config, collected_at, verbose=verbose)
    watchlist, watchlist_repository = build_watchlist_use_case(
        watchlist_config, collected_at, verbose=verbose
    )
    run = search_config.run
    bundle = ResearchBundleFilesOutput(
        Path(run.export.out_dir) / "research",
        runtime.compact_run_id(collected_at),
        {
            "collected_at": collected_at,
            "provider": run.provider,
            "seed_keywords": list(search_config.keywords),
            "synonyms": {key: list(value) for key, value in search_config.synonyms.items()},
            "window_days": run.search.window_days,
            "notes_per_account": run.creator.notes_per_account,
            "max_total": run.watchlist.max_total if run.watchlist else 0,
        },
    )
    return RunResearch(search, watchlist, bundle), (search_repository, watchlist_repository)


def build_backfill_use_case(config: LoadedSearchConfig, collected_at: str, *, verbose: bool):
    run = config.run
    if not run.store.enabled:
        raise ValueError("媒体补抓需要 store.enabled=true")
    if run.provider != "mediacrawler":
        raise ValueError("媒体补抓需要 provider=mediacrawler")
    if not run.mediacrawler_dir or not Path(run.mediacrawler_dir).exists():
        raise ValueError(f"MediaCrawler 目录不可用：{run.mediacrawler_dir or '<empty>'}")
    adapter = runtime.build_adapter(run)
    configure_logging(
        run.logging.model_dump(),
        verbose=verbose,
        run_id=collected_at,
        provider=adapter.provider_name,
    )
    collector = ProgressContentDetailCollector(XhsContentDetailCollector(adapter), adapter)
    registry = PlatformRegistry()
    registry.register_content_detail_collector(collector)
    repository = MySQLResearchRepository(run.store.database)
    return BackfillMedia(registry.content_detail_collector("xhs"), repository), repository
