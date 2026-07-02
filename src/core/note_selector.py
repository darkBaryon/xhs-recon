"""每账号选典型笔记（v0：按互动加权取 top-N）。"""

from datetime import datetime

from src.models import Note, TypicalNote


def _note_score(n: Note) -> float:
    return float(n.like_count + 2 * n.collect_count + 3 * n.comment_count)


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recency_score(n: Note, now: datetime, half_life_days: int) -> float:
    published_at = _parse_iso(n.published_at)
    age_days = 365
    if published_at is not None:
        age_days = max((now - published_at).days, 0)
    return _note_score(n) * 0.5 ** (age_days / half_life_days)


def select_typical_notes(
    notes: list[Note],
    top_per_account: int = 2,
    half_life_days: int = 0,
    now_iso: str | None = None,
) -> list[TypicalNote]:
    now = _parse_iso(now_iso) if now_iso else None
    recency_enabled = half_life_days > 0 and now is not None
    if recency_enabled:
        assert now is not None

        def score(note: Note) -> float:
            return _recency_score(note, now, half_life_days)

    else:
        score = _note_score

    by_acc: dict[str, list[Note]] = {}
    for n in notes:
        by_acc.setdefault(n.account_id, []).append(n)

    out: list[TypicalNote] = []
    for acc_id, acc_notes in by_acc.items():
        ranked = sorted(acc_notes, key=score, reverse=True)
        for n in ranked[:top_per_account]:
            out.append(
                TypicalNote(
                    account_id=acc_id,
                    note_id=n.note_id,
                    title=n.title,
                    url=n.url,
                    note_score=score(n),
                    selection_reason=(
                        "top by interaction×recency" if recency_enabled else "top by interaction"
                    ),
                )
            )
    return out
