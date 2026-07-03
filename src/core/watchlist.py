"""专业账号 watchlist 合成。

core 层只处理已经归一化的账号 id；平台 URL 解析停留在 adapter 边界。
"""

import logging

from src.models import AccountRank, WatchAccount

logger = logging.getLogger(__name__)


def build_watchlist(
    ranked: list[AccountRank],
    manual_ids: list[str],
    auto_top_n: int,
    max_total: int,
    manual_nicknames: dict[str, str] | None = None,
) -> list[WatchAccount]:
    nickname_by_id = {r.account_id: r.nickname for r in ranked}
    manual_nicknames = manual_nicknames or {}
    accounts: list[WatchAccount] = []
    seen: set[str] = set()

    for account_id in manual_ids:
        if account_id in seen:
            continue
        seen.add(account_id)
        accounts.append(
            WatchAccount(
                account_id=account_id,
                nickname=manual_nicknames.get(account_id) or nickname_by_id.get(account_id, ""),
                source="manual",
            )
        )

    for rank in ranked[: max(0, auto_top_n)]:
        if rank.account_id in seen:
            continue
        seen.add(rank.account_id)
        accounts.append(
            WatchAccount(account_id=rank.account_id, nickname=rank.nickname, source="auto")
        )

    cap = max(0, max_total)
    dropped = accounts[cap:]
    if dropped:
        # 静默砍尾会无声丢账号（含 manual 手写项）——超限必须留痕
        logger.warning(
            "watchlist 超上限 max_total=%d，截掉 %d 个：%s",
            max_total,
            len(dropped),
            ",".join(a.account_id for a in dropped),
        )
    return accounts[:cap]
