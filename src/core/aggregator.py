"""跨 FetchResult 聚合：笔记按 note_id 去重、账号按 account_id 去重，
source_keywords 跨关键词合并保序，note_count 派生。平台无关。
"""

from src.models import Account, FetchResult, Note


def _merge_keywords(base: list[str], extra: list[str]) -> list[str]:
    out = list(base)
    for kw in extra:
        if kw not in out:
            out.append(kw)
    return out


def aggregate(results: list[FetchResult]) -> tuple[list[Note], list[Account]]:
    nick: dict[str, str] = {}
    for r in results:
        if not r.ok:
            continue
        for a in r.accounts:
            nick.setdefault(a.account_id, a.nickname)

    notes_by_id: dict[str, Note] = {}
    for r in results:
        if not r.ok:
            continue
        for n in r.notes:
            existing = notes_by_id.get(n.note_id)
            if existing is None:
                notes_by_id[n.note_id] = n.model_copy(deep=True)
            else:
                existing.source_keywords = _merge_keywords(
                    existing.source_keywords, n.source_keywords
                )
    notes = list(notes_by_id.values())

    accounts_by_id: dict[str, Account] = {}
    for n in notes:
        acc = accounts_by_id.get(n.account_id)
        if acc is None:
            accounts_by_id[n.account_id] = Account(
                account_id=n.account_id,
                nickname=nick.get(n.account_id, ""),
                source_keywords=list(n.source_keywords),
                note_count=1,
                first_seen_at=n.collected_at,
                last_seen_at=n.collected_at,
            )
        else:
            acc.note_count += 1
            acc.source_keywords = _merge_keywords(acc.source_keywords, n.source_keywords)
            acc.first_seen_at = min(acc.first_seen_at, n.collected_at)
            acc.last_seen_at = max(acc.last_seen_at, n.collected_at)

    return notes, list(accounts_by_id.values())
