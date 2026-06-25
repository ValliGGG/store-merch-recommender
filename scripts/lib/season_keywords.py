"""Keyword-based seasonal detection for products without custom.prilezitost.

ARTMIE SK product titles are in Slovak. We use lemma-friendly substrings
(diacritic-insensitive) per season. Conservative — only tag when a high-signal
keyword appears, since false positives hide products from sale.
"""
from __future__ import annotations

import unicodedata


def fold(s: str) -> str:
    """Lowercase + strip diacritics so 'Vianočný' and 'vianocny' both match 'vianoc'."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s.lower())
        if unicodedata.category(c) != "Mn"
    )


# Each entry: season_tag -> list of folded substrings.
# Includes Slovak (primary) plus a few English/international terms used in titles.
KEYWORDS: dict[str, list[str]] = {
    "season:christmas": [
        "vianoc",      # vianočný, vianoce, vianočná
        "vianocn",
        "christmas",
        "xmas",
        "advent",
        "stromcek",    # stromček (tree)
        "stromčekov",
        "betlehem",
        "santa",
        "mikulas",     # Mikuláš
        "salasov",     # šalasov
        "ozdob na strom",
    ],
    "season:easter": [
        "velkonoc",    # veľkonočný
        "vajicko",     # vajíčko
        "vajicka",
        "kraslic",     # kraslica
        "easter",
        "zajacik",     # zajačik
        "baranci",     # baránci
        "korbac",      # korbáč
    ],
    "season:halloween": [
        "halloween",
        "halloweens",
        "dyna",        # dyňa = pumpkin (also = stuffing material — risk; only flag when clearly halloween)
        "tekvica",
        "duch",        # ghost — too generic alone; require co-occurrence below
        "strasidel",   # strašidelný
    ],
    "season:valentine": [
        "valent",      # Valentín
        "valentine",
        "ja t'a lubim",
        "love",        # too generic alone — require co-occurrence
    ],
    "season:back-to-school": [
        "spat do skoly",
        "back to school",
        "skolsk",      # školský
        "skola",       # too generic alone — needs co-occurrence with another back-to-school signal
    ],
}

# Some keywords are too ambiguous to flag on their own. Require ≥2 hits in any
# combination from these "weak" buckets to assign that season tag.
WEAK_KEYWORDS: dict[str, list[str]] = {
    "season:halloween": ["duch", "tekvica", "dyna"],
    "season:valentine": ["love", "srdce", "srdiečk"],
    "season:back-to-school": ["skola", "ceruzk", "zosit"],
}


def detect(text: str) -> list[str]:
    """Return season tags inferred from a product's title (+ optional description)."""
    if not text:
        return []
    folded = fold(text)
    out: list[str] = []
    for season, kws in KEYWORDS.items():
        weak = set(WEAK_KEYWORDS.get(season, []))
        strong_hit = any(kw in folded for kw in kws if kw not in weak)
        if strong_hit:
            out.append(season)
            continue
        # Otherwise need ≥2 weak hits to count
        weak_hits = sum(1 for kw in kws if kw in weak and kw in folded)
        if weak_hits >= 2:
            out.append(season)
    return out
