"""Resolve product brand from configurable selectors.

Returns the brand value (str) and a boolean is_artmie flag.
"""
from __future__ import annotations

from typing import Iterable


def resolve(
    *,
    metafields: Iterable[dict],
    tags: list[str],
    selectors: list[dict],
) -> tuple[str | None, bool]:
    """metafields: iterable of {namespace,key,value} dicts already pulled from Shopify."""
    mf_lookup: dict[tuple[str, str], str] = {}
    for mf in metafields:
        ns = mf.get("namespace")
        k  = mf.get("key")
        if ns and k:
            mf_lookup[(ns, k)] = mf.get("value") or ""

    tags_lower = {t.lower() for t in tags or []}

    for sel in selectors:
        if sel["type"] == "metafield":
            v = mf_lookup.get((sel["namespace"], sel["key"]))
            if v is not None and v.strip() == sel["equals"]:
                return v, True
        elif sel["type"] == "tag":
            if sel["equals"].lower() in tags_lower:
                return sel["equals"], True

    # Not Artmie — but if custom.znacka exists, return it as the brand value (informational)
    znacka = mf_lookup.get(("custom", "znacka"))
    return (znacka.strip() if znacka else None), False
