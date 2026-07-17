"""ResearchAdapter 端口：定义在 core，由 adapters 实现，pipelines 注入。

core 只认这个抽象端口与领域模型，永不 import 具体 adapter，也不出现平台名。
"""

from abc import ABC, abstractmethod

from src.models import FetchResult, TypicalNote


class ResearchAdapter(ABC):
    provider_name: str

    @abstractmethod
    def search(self, keyword: str, page: int, limit: int, collected_at: str) -> FetchResult: ...

    def fetch_comments(
        self, notes: list[TypicalNote], limit: int, collected_at: str
    ) -> FetchResult:
        # 期3 才必需；期1/期2 adapter 不必覆盖
        raise NotImplementedError

    def fetch_creator_notes(
        self,
        account_ids: list[str],
        limit: int,
        collected_at: str,
        with_comments: bool = True,
    ) -> FetchResult:
        raise NotImplementedError
