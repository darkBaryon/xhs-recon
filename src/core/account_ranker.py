"""账号打分（v0 简单加权，权重可配；精度非目标，允许各期调）。"""

from src.models import Account, AccountRank, Note

DEFAULT_WEIGHTS: dict[str, float] = {
    "note_count": 10.0,
    "keyword_hit": 5.0,
    "interaction": 0.01,
}


def _interaction(n: Note) -> int:
    return n.like_count + n.collect_count + n.comment_count


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
