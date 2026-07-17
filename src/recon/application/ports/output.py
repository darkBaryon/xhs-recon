from typing import Protocol

from ...domain.research import (
    AccountAnalysis,
    ResearchAnalysis,
    SearchAnalysis,
    WatchlistAnalysis,
)


class AccountOutput(Protocol):
    def write(self, analysis: AccountAnalysis) -> dict[str, str]: ...


class SearchOutput(Protocol):
    def write(self, analysis: SearchAnalysis) -> dict[str, str]: ...


class WatchlistOutput(Protocol):
    def write(self, analysis: WatchlistAnalysis) -> dict[str, str]: ...


class ResearchBundleOutput(Protocol):
    def write(self, analysis: ResearchAnalysis) -> dict[str, str]: ...
