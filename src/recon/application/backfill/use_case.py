import logging
from dataclasses import dataclass

from ..ports.collection import ContentDetailCollectionRequest, ContentDetailCollector
from ..ports.repository import BackfillRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BackfillRequest:
    collected_at: str
    batch_size: int = 30
    limit: int = 0


@dataclass(frozen=True, slots=True)
class BackfillReceipt:
    requested: int
    saved: int
    failures: int


class BackfillMedia:
    def __init__(self, collector: ContentDetailCollector, repository: BackfillRepository) -> None:
        self.collector = collector
        self.repository = repository

    def execute(self, request: BackfillRequest) -> BackfillReceipt:
        candidates = self.repository.contents_missing_media(request.limit)
        saved = 0
        failures = 0
        batch_size = max(request.batch_size, 1)
        logger.info("媒体补抓开始：候选 %d · 每批 %d", len(candidates), batch_size)
        for offset in range(0, len(candidates), batch_size):
            result = self.collector.collect_content_details(
                ContentDetailCollectionRequest(
                    contents=candidates[offset : offset + batch_size],
                    collected_at=request.collected_at,
                    fetch_comments=False,
                )
            )
            self.repository.save_backfill(result)
            saved += sum(bool(content.image_paths) for content in result.contents)
            failures += len(result.failures)
            logger.info(
                "媒体补抓批次 %d/%d：详情 %d · 有图 %d · 失败 %d",
                offset // batch_size + 1,
                (len(candidates) + batch_size - 1) // batch_size,
                len(result.contents),
                sum(bool(content.image_paths) for content in result.contents),
                len(result.failures),
            )
        return BackfillReceipt(len(candidates), saved, failures)
