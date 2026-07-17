from typing import Protocol


class Sleeper(Protocol):
    """批次间节流端口；application 不依赖具体的系统时钟实现。"""

    def sleep(self, seconds: int) -> None: ...
