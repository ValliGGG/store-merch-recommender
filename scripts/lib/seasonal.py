"""Seasonal window logic.

Two responsibilities:
1. Map an occasion-metafield value (Slovak, e.g. "Vianoce") to a season tag.
2. Decide whether a given season tag is currently in-season.

Easter is dynamic — computed via the canonical Computus algorithm so we don't
depend on dateutil for a single call.
"""
from __future__ import annotations

from datetime import date, timedelta


def easter_date(year: int) -> date:
    """Anonymous Gregorian computus."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    L = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * L) // 451
    month = (h + L - 7 * m + 114) // 31
    day = ((h + L - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def in_window_static(today: date, frm: str, to: str) -> bool:
    """frm/to are 'MM-DD' strings. Window may wrap year boundary (e.g. 10-15 -> 01-06)."""
    mm_f, dd_f = (int(x) for x in frm.split("-"))
    mm_t, dd_t = (int(x) for x in to.split("-"))
    start = date(today.year, mm_f, dd_f)
    end   = date(today.year, mm_t, dd_t)
    if start <= end:
        return start <= today <= end
    # Wrap (start > end): in-season if after start OR before end (in next-year terms)
    return today >= start or today <= end


def in_window_easter(today: date, from_offset_weeks: int, to_offset_days: int) -> bool:
    e = easter_date(today.year)
    start = e + timedelta(weeks=from_offset_weeks)
    end   = e + timedelta(days=to_offset_days)
    return start <= today <= end


def is_in_season(season_tag: str, season_cfg: dict, today: date | None = None) -> bool:
    today = today or date.today()
    spec = season_cfg["windows"].get(season_tag)
    if not spec:
        return True   # unknown season → don't hide
    if "relative_to" in spec and spec["relative_to"] == "easter":
        return in_window_easter(
            today,
            from_offset_weeks=int(spec["from_offset_weeks"]),
            to_offset_days=int(spec["to_offset_days"]),
        )
    return in_window_static(today, spec["from"], spec["to"])


def occasions_to_seasons(occasions: list[str], season_cfg: dict) -> list[str]:
    """Map raw occasion values to internal season tags (per-store, localized).

    A single occasion value may itself be a comma-joined list (e.g. the Czech
    "Vánoce, Velikonoce"), so each value is split on commas before mapping.
    Matching is case-insensitive.
    """
    mapping = season_cfg["occasion_to_season"]
    out: list[str] = []
    for o in occasions:
        parts = [p.strip() for p in str(o).split(",") if p.strip()] or [str(o).strip()]
        for p in parts:
            tag = mapping.get(p) or mapping.get(p.lower())
            if tag and tag not in out:
                out.append(tag)
    return out
