"""账号打分（v0 简单加权，权重可配；精度非目标，允许各期调）。"""

from src.core.time_window import filter_notes
from src.models import Account, AccountRank, Note, WatchAccount

DEFAULT_WEIGHTS: dict[str, float] = {
    "note_count": 10.0,
    "keyword_hit": 5.0,
    "interaction": 0.01,
}

DEFAULT_PROFILE_WEIGHTS: dict[str, float] = {
    "vertical": 10.0,
    "activity": 1.0,
}


def _interaction(n: Note) -> int:
    return n.like_count + n.collect_count + n.comment_count


def _matches_domain(note: Note, keywords: list[str]) -> bool:
    haystack = " ".join([note.title, note.body, *note.tags]).casefold()
    return any(keyword.casefold() in haystack for keyword in keywords if keyword)


def rank_accounts(
    accounts: list[Account],
    notes: list[Note],
    weights: dict[str, float] | None = None,
) -> list[AccountRank]:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    notes_by_acc: dict[str, list[Note]] = {}
    for n in notes:
        notes_by_acc.setdefault(n.account_id, []).append(n)

    ranks: list[AccountRank] = []
    for acc in accounts:
        acc_notes = notes_by_acc.get(acc.account_id, [])
        relevant = len(acc_notes)
        avg_inter = sum(_interaction(n) for n in acc_notes) / relevant if relevant else 0.0
        kw_hits = len(acc.source_keywords)
        score = (
            w["note_count"] * relevant + w["keyword_hit"] * kw_hits + w["interaction"] * avg_inter
        )
        ranks.append(
            AccountRank(
                account_id=acc.account_id,
                nickname=acc.nickname,
                relevant_note_count=relevant,
                keyword_hit_count=kw_hits,
                avg_interaction=avg_inter,
                account_score=score,
                note_ids=[n.note_id for n in acc_notes],
            )
        )
    ranks.sort(key=lambda r: r.account_score, reverse=True)
    return ranks


def profile_accounts(
    watchlist: list[WatchAccount],
    creator_notes: list[Note],
    domain_keywords: list[str],
    window_days: int,
    now_iso: str,
    weights: dict[str, float] | None = None,
) -> list[AccountRank]:
    w = {**DEFAULT_PROFILE_WEIGHTS, **(weights or {})}
    notes_by_acc: dict[str, list[Note]] = {}
    for note in creator_notes:
        notes_by_acc.setdefault(note.account_id, []).append(note)

    profiles: list[AccountRank] = []
    for account in watchlist:
        account_notes = notes_by_acc.get(account.account_id, [])
        matched = sum(1 for note in account_notes if _matches_domain(note, domain_keywords))
        vertical_ratio = matched / len(account_notes) if account_notes else 0.0
        recent_notes, _stats = filter_notes(account_notes, window_days, now_iso)
        recent_count = len(recent_notes)
        profile_score = w["vertical"] * vertical_ratio + w["activity"] * recent_count
        profiles.append(
            AccountRank(
                account_id=account.account_id,
                nickname=account.nickname,
                relevant_note_count=0,
                keyword_hit_count=0,
                avg_interaction=0.0,
                account_score=0.0,
                note_ids=[],
                vertical_ratio=vertical_ratio,
                recent_note_count=recent_count,
                profile_score=profile_score,
            )
        )
    return profiles
