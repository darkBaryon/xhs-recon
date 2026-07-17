import logging
from dataclasses import dataclass

from ...domain.content import (
    AccountCollectionResult,
    AccountTarget,
    CollectionFailure,
)
from ...domain.research import WatchlistAnalysis, WatchlistReceipt
from ..ports.collection import (
    ContentDetailCollectionRequest,
    ContentDetailCollector,
    CreatorFeedCollectionRequest,
    CreatorFeedCollector,
)
from ..ports.output import WatchlistOutput
from ..ports.repository import WatchlistRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WatchlistRequest:
    targets: tuple[AccountTarget, ...]
    collected_at: str
    max_notes: int = 10
    batch_size: int = 0
    refresh_days: int = 0
    comments_refresh_days: int = 0
    fetch_comments: bool = True


class SyncWatchlist:
    def __init__(
        self,
        creator_feeds: CreatorFeedCollector,
        content_details: ContentDetailCollector,
        repository: WatchlistRepository,
        output: WatchlistOutput,
    ) -> None:
        self.creator_feeds = creator_feeds
        self.content_details = content_details
        self.repository = repository
        self.output = output

    def execute(self, request: WatchlistRequest) -> WatchlistReceipt:
        if not request.targets:
            raise ValueError("watchlist 中没有手工账号")
        due = self.repository.due_targets(
            request.targets,
            request.collected_at,
            request.refresh_days,
            request.batch_size,
        )
        logger.info("Watchlist 开始：到期 %d/%d 个账号", len(due), len(request.targets))
        if not due:
            return self._receipt(request, due, ())

        known_by_account = {}
        comment_due_by_account = {}
        for target in due:
            account_id = target.id.external_id
            known_by_account[account_id] = self.repository.known_content_ids(target)
            comment_due_by_account[account_id] = (
                self.repository.content_ids_needing_comments(
                    target,
                    request.collected_at,
                    request.comments_refresh_days,
                )
                if request.fetch_comments
                else frozenset()
            )
            logger.info(
                "Watchlist 账号：%s · 已知帖子 %d · 评论待刷新 %d",
                target.nickname or account_id,
                len(known_by_account[account_id]),
                len(comment_due_by_account[account_id]),
            )

        feeds = self.creator_feeds.collect_creator_feeds(
            CreatorFeedCollectionRequest(
                targets=due,
                collected_at=request.collected_at,
                max_notes=request.max_notes,
            )
        )
        detail_references = tuple(
            content
            for content in feeds.contents
            if content.creator_id is not None
            and (
                content.id.external_id not in known_by_account[content.creator_id.external_id]
                or content.id.external_id in comment_due_by_account[content.creator_id.external_id]
            )
        )
        logger.info(
            "Watchlist 批量列表完成：账号 %d · 列表帖子 %d · 需详情 %d",
            len(due),
            len(feeds.contents),
            len(detail_references),
        )
        details = (
            self.content_details.collect_content_details(
                ContentDetailCollectionRequest(
                    contents=detail_references,
                    collected_at=request.collected_at,
                    fetch_comments=request.fetch_comments,
                )
            )
            if detail_references
            else AccountCollectionResult(platform=feeds.platform, collected_at=request.collected_at)
        )
        collections = self._partition_results(
            request,
            due,
            feeds,
            details,
            detail_references,
        )
        for result in collections:
            self.repository.save_watchlist(
                result,
                comments_fetched=request.fetch_comments and not result.failures,
            )
            logger.info(
                "Watchlist 账号完成：新帖 %d · 评论 %d · 失败 %d",
                len(result.contents),
                len(result.comments),
                len(result.failures),
            )
        return self._receipt(request, due, collections)

    @staticmethod
    def _partition_results(request, due, feeds, details, detail_references):
        feed_creators = {creator.id: creator for creator in feeds.creators}
        detail_creators = {creator.id: creator for creator in details.creators}
        feed_failures = {failure.target_external_id: failure for failure in feeds.failures}
        accounts_with_details = {
            content.creator_id.external_id
            for content in detail_references
            if content.creator_id is not None
        }
        collections = []
        for target in due:
            account_id = target.id.external_id
            creator = feed_creators.get(target.id) or detail_creators.get(target.id)
            contents = tuple(
                content for content in details.contents if content.creator_id == target.id
            )
            content_ids = {content.id for content in contents}
            comments = tuple(
                comment for comment in details.comments if comment.content_id in content_ids
            )
            failures = []
            if account_id in feed_failures:
                failures.append(feed_failures[account_id])
            if account_id in accounts_with_details:
                failures.extend(
                    CollectionFailure(account_id, failure.message) for failure in details.failures
                )
            collections.append(
                AccountCollectionResult(
                    platform=feeds.platform,
                    collected_at=request.collected_at,
                    creators=(creator,) if creator else (),
                    contents=contents,
                    comments=comments,
                    failures=tuple(failures),
                )
            )
        return tuple(collections)

    def _receipt(self, request, due, collections):
        analysis = WatchlistAnalysis(
            requested=request.targets,
            due=tuple(target.id for target in due),
            collections=tuple(collections),
        )
        paths = self.output.write(analysis)
        logger.info(
            "Watchlist 完成：新帖 %d · 输出 %d 个文件",
            sum(len(collection.contents) for collection in collections),
            len(paths),
        )
        return WatchlistReceipt(analysis=analysis, output_paths=paths)
