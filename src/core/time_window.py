"""时间窗过滤（平台无关，只依赖 Note 的 published_at）。"""

from datetime import datetime

from pydantic import BaseModel

from src.models import Note


class WindowFilterStats(BaseModel):
    kept: int
    out_of_window: int
    missing_time: int


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def filter_notes(
    notes: list[Note], window_days: int, now_iso: str
) -> tuple[list[Note], WindowFilterStats]:
    if window_days <= 0:
        return notes, WindowFilterStats(kept=len(notes), out_of_window=0, missing_time=0)

    now = _parse_iso(now_iso)
    if now is None:
        raise ValueError("now_iso must be a valid ISO datetime")

    kept: list[Note] = []
    out_of_window = 0
    missing_time = 0

    for note in notes:
        published_at = _parse_iso(note.published_at)
        if published_at is None:
            missing_time += 1
            continue

        age_days = (now - published_at).total_seconds() / 86400
        if age_days <= window_days:
            kept.append(note)
        else:
            out_of_window += 1

    return kept, WindowFilterStats(
        kept=len(kept),
        out_of_window=out_of_window,
        missing_time=missing_time,
    )
