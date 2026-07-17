import logging
from dataclasses import dataclass

from ...domain.content import Content, Creator, SearchCollectionResult
from ...domain.policies.keywords import expand_keywords
from ...domain.policies.ranking import rank_creators
from ...domain.policies.time_window import filter_contents
from ...domain.research import SearchAnalysis, SearchReceipt
from ..ports.clock import Sleeper
from ..ports.collection import SearchCollectionRequest, SearchCollector
from ..ports.output import SearchOutput
from ..ports.repository import SearchRepository

logger = logging.getLogger(__name__)

_STOP_SIGNALS = ("风险信号", "风控", "验证码", "登录已过期", "采集已熔断")


@dataclass(frozen=True, slots=True)
class SearchRequest:
    keywords: tuple[str, ...]
    collected_at: str
    synonyms: dict[str, tuple[str, ...]] | None = None
    pages: int = 1
    limit: int = 20
    window_days: int = 0
    batch_size: int = 0
    pause_between_batches_sec: int = 0
    ranking_weights: dict[str, float] | None = None


class SearchContents:
    def __init__(
        self,
        collector: SearchCollector,
        repository: SearchRepository,
        output: SearchOutput,
        sleeper: Sleeper | None = None,
    ):
        self.collector = collector
        self.repository = repository
        self.output = output
        self.sleeper = sleeper

    def execute(self, request: SearchRequest) -> SearchReceipt:
        keywords = expand_keywords(request.keywords, request.synonyms)
        if not keywords:
            raise ValueError("搜索配置中没有关键词")
        logger.info(
            "关键词搜索开始：%d 个实际关键词 · %d 页/词 · %d 条/页 · 时间窗 %s",
            len(keywords),
            request.pages,
            request.limit,
            f"{request.window_days} 天" if request.window_days > 0 else "不限",
        )
        collections = []
        stopped = False
        requests = tuple(
            SearchCollectionRequest(
                keyword=keyword,
                collected_at=request.collected_at,
                pages=request.pages,
                limit=request.limit,
            )
            for keyword in keywords
        )
        batch_size = request.batch_size if request.batch_size > 0 else len(requests)
        batch_count = (len(requests) + batch_size - 1) // batch_size
        for offset in range(0, len(requests), batch_size):
            batch = requests[offset : offset + batch_size]
            logger.info(
                "搜索批次 %d/%d：%s",
                offset // batch_size + 1,
                batch_count,
                "、".join(item.keyword for item in batch),
            )
            for result in self.collector.collect_search_batch(batch):
                before_filter = len(result.contents)
                filtered = filter_contents(
                    result.contents, request.window_days, request.collected_at
                )
                if filtered != result.contents:
                    result = SearchCollectionResult(
                        platform=result.platform,
                        keyword=result.keyword,
                        collected_at=result.collected_at,
                        creators=result.creators,
                        contents=filtered,
                        failures=result.failures,
                    )
                self.repository.save_search(result)
                collections.append(result)
                logger.info(
                    "关键词「%s」完成：帖子 %d%s · 账号 %d · 失败 %d · 归属已保存",
                    result.keyword,
                    len(result.contents),
                    f"（时间窗过滤 {before_filter - len(result.contents)}）"
                    if before_filter != len(result.contents)
                    else "",
                    len(result.creators),
                    len(result.failures),
                )
                if any(
                    any(signal in failure.message for signal in _STOP_SIGNALS)
                    for failure in result.failures
                ):
                    stopped = True
            if stopped:
                logger.error("检测到平台风险信号：停止后续关键词批次，不自动重试")
                break
            batch_number = offset // batch_size + 1
            if batch_number < batch_count and request.pause_between_batches_sec > 0:
                if self.sleeper is None:
                    raise RuntimeError("配置了搜索批次暂停，但未注入 Sleeper")
                logger.info(
                    "搜索批次 %d/%d 完成：暂停 %d 秒后继续",
                    batch_number,
                    batch_count,
                    request.pause_between_batches_sec,
                )
                self.sleeper.sleep(request.pause_between_batches_sec)

        creators_by_id: dict = {}
        contents_by_id: dict = {}
        for collection in collections:
            for creator in collection.creators:
                creators_by_id.setdefault(creator.id, creator)
            for content in collection.contents:
                contents_by_id.setdefault(content.id, content)
        creators: tuple[Creator, ...] = tuple(creators_by_id.values())
        contents: tuple[Content, ...] = tuple(contents_by_id.values())
        analysis = SearchAnalysis(
            keywords=keywords,
            collections=tuple(collections),
            creators=creators,
            contents=contents,
            ranks=rank_creators(creators, contents, tuple(collections), request.ranking_weights),
            window_days=request.window_days,
        )
        logger.info(
            "搜索汇总完成：去重帖子 %d · 账号 %d · 关键词关系 %d",
            len(contents),
            len(creators),
            sum(len(collection.contents) for collection in collections),
        )
        output_paths = self.output.write(analysis)
        logger.info("搜索分析输出完成：%d 个文件", len(output_paths))
        return SearchReceipt(analysis=analysis, output_paths=output_paths)
