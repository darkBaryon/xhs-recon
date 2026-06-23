"""每账号选典型笔记（v0：按互动加权取 top-N）。"""

from src.models import Note, TypicalNote


def _note_score(n: Note) -> float:
    return float(n.like_count + 2 * n.collect_count + 3 * n.comment_count)


def select_typical_notes(notes: list[Note], top_per_account: int = 2) -> list[TypicalNote]:
    by_acc: dict[str, list[Note]] = {}
    for n in notes:
        by_acc.setdefault(n.account_id, []).append(n)

    out: list[TypicalNote] = []
    for acc_id, acc_notes in by_acc.items():
        ranked = sorted(acc_notes, key=_note_score, reverse=True)
        for n in ranked[:top_per_account]:
            out.append(
                TypicalNote(
                    account_id=acc_id,
                    note_id=n.note_id,
                    title=n.title,
                    url=n.url,
                    note_score=_note_score(n),
                    selection_reason="top by interaction",
                )
            )
    return out
