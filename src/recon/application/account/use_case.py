import logging
from dataclasses import dataclass

from ...domain.content import AccountCollectionResult, AccountTarget
from ...domain.policies.aggregate import summarize_accounts
from ...domain.research import AccountAnalysis, AccountAnalysisReceipt
from ..ports.collection import (
    ContentDetailCollectionRequest,
    ContentDetailCollector,
    CreatorFeedCollectionRequest,
    CreatorFeedCollector,
)
from ..ports.output import AccountOutput
from ..ports.repository import AccountRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AnalyzeAccountsRequest:
    targets: tuple[AccountTarget, ...]
    collected_at: str
    max_notes: int | None = None
    fetch_comments: bool = False


class AnalyzeAccounts:
    def __init__(
        self,
        creator_feeds: CreatorFeedCollector,
        content_details: ContentDetailCollector,
        repository: AccountRepository,
        output: AccountOutput,
    ) -> None:
        self.creator_feeds = creator_feeds
        self.content_details = content_details
        self.repository = repository
        self.output = output

    def execute(self, request: AnalyzeAccountsRequest) -> AccountAnalysisReceipt:
        if not request.targets:
            raise ValueError("账号分析配置中没有账号")
        logger.info(
            "账号分析开始：%d 个账号 · 每账号上限 %s · 评论 %s",
            len(request.targets),
            request.max_notes if request.max_notes is not None else "全部",
            "开启" if request.fetch_comments else "关闭",
        )
        feeds = self.creator_feeds.collect_creator_feeds(
            CreatorFeedCollectionRequest(
                targets=request.targets,
                collected_at=request.collected_at,
                max_notes=request.max_notes,
            )
        )
        details = (
            self.content_details.collect_content_details(
                ContentDetailCollectionRequest(
                    contents=feeds.contents,
                    collected_at=request.collected_at,
                    fetch_comments=request.fetch_comments,
                )
            )
            if feeds.contents
            else AccountCollectionResult(platform=feeds.platform, collected_at=request.collected_at)
        )
        creators = {creator.id: creator for creator in details.creators}
        creators.update({creator.id: creator for creator in feeds.creators})
        collection = AccountCollectionResult(
            platform=feeds.platform,
            collected_at=request.collected_at,
            creators=tuple(creators.values()),
            contents=details.contents,
            comments=details.comments,
            failures=feeds.failures + details.failures,
        )
        logger.info(
            "账号采集完成：账号 %d · 帖子 %d · 评论 %d · 失败 %d",
            len(collection.creators),
            len(collection.contents),
            len(collection.comments),
            len(collection.failures),
        )
        analysis = AccountAnalysis(
            collection=collection,
            summaries=summarize_accounts(collection),
        )
        self.repository.save(collection)
        logger.info(
            "账号数据保存完成：账号 %d · 帖子 %d",
            len(collection.creators),
            len(collection.contents),
        )
        output_paths = self.output.write(analysis)
        logger.info("账号分析输出完成：%d 个文件", len(output_paths))
        return AccountAnalysisReceipt(analysis=analysis, output_paths=output_paths)
