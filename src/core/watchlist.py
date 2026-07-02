"""专业账号 watchlist 合成。

core 层只处理已经归一化的账号 id；平台 URL 解析停留在 adapter 边界。
"""

from src.models import AccountRank, WatchAccount


def build_watchlist(
    ranked: list[AccountRank],
    manual_ids: list[str],
    auto_top_n: int,
    max_total: int,
) -> list[WatchAccount]:
    nickname_by_id = {r.account_id: r.nickname for r in ranked}
    accounts: list[WatchAccount] = []
    seen: set[str] = set()

    for account_id in manual_ids:
        if account_id in seen:
            continue
        seen.add(account_id)
        accounts.append(
            WatchAccount(
                account_id=account_id,
                nickname=nickname_by_id.get(account_id, ""),
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

    return accounts[: max(0, max_total)]
