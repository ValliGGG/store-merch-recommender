"""Apply / clear the hidden:off-season tag on products based on current date.

Reads `season_tags` from the local product cache (populated by 02b).
For each product with at least one season tag:
  - If ALL of its seasons are currently OUT of season -> tag hidden:off-season
  - If ANY of its seasons is currently IN season       -> remove hidden:off-season

Tracks every tag we apply in `managed_tags` so we never strip a tag we
didn't add (manual additions are preserved).

Usage:
    python scripts/03a_apply_seasonal_mask.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg_mod, db as db_mod, seasonal
from lib.shopify_client import ShopifyClient

ADD_TAGS_M = """
mutation Add($id: ID!, $tags: [String!]!) {
  tagsAdd(id: $id, tags: $tags) {
    node { id }
    userErrors { field message }
  }
}
"""
REMOVE_TAGS_M = """
mutation Remove($id: ID!, $tags: [String!]!) {
  tagsRemove(id: $id, tags: $tags) {
    node { id }
    userErrors { field message }
  }
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=None, help="store code (default: sk / $ARTMIE_STORE)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = cfg_mod.load(args.store)
    print(f"[{cfg.store}] shop: {cfg.shop.store_url}")
    client = ShopifyClient(cfg.shop)
    conn = db_mod.connect(cfg.db_path)
    db_mod.ensure_schema(conn)

    season_cfg = cfg.seasonal
    hide_tag = season_cfg["hide_tag"]
    today = datetime.now(timezone.utc).date()

    rows = conn.execute(
        "SELECT id, title, tags, season_tags FROM products WHERE season_tags != ''"
    ).fetchall()

    to_hide: list[tuple[str, str]] = []
    to_unhide: list[tuple[str, str]] = []
    for r in rows:
        tags = [t for t in (r["tags"] or "").split(",") if t]
        currently_hidden = hide_tag in tags
        season_tags = [t for t in r["season_tags"].split(",") if t]
        in_season = any(seasonal.is_in_season(t, season_cfg, today) for t in season_tags)
        should_hide = not in_season
        if should_hide and not currently_hidden:
            to_hide.append((r["id"], r["title"]))
        elif (not should_hide) and currently_hidden:
            to_unhide.append((r["id"], r["title"]))

    print(f"products needing hide:   {len(to_hide)}")
    print(f"products needing unhide: {len(to_unhide)}")
    if args.dry_run:
        for pid, title in to_hide[:5]:
            print(f"  [hide]   {title[:70]}")
        for pid, title in to_unhide[:5]:
            print(f"  [unhide] {title[:70]}")
        return

    with db_mod.run(conn, "mask", notes=f"hide={len(to_hide)} unhide={len(to_unhide)}"):
        # tagsAdd / tagsRemove are per-resource mutations.  ~200 IO calls each.
        for pid, title in to_hide:
            d = client.execute(ADD_TAGS_M, {"id": pid, "tags": [hide_tag]})
            errs = d["tagsAdd"]["userErrors"]
            if errs:
                print(f"  warn add {title[:50]}: {errs}", file=sys.stderr)
                continue
            conn.execute(
                "INSERT OR REPLACE INTO managed_tags(product_id, tag, applied_at) VALUES (?,?,?)",
                (pid, hide_tag, db_mod.now_iso()),
            )
        for pid, title in to_unhide:
            d = client.execute(REMOVE_TAGS_M, {"id": pid, "tags": [hide_tag]})
            errs = d["tagsRemove"]["userErrors"]
            if errs:
                print(f"  warn remove {title[:50]}: {errs}", file=sys.stderr)
                continue
            conn.execute(
                "DELETE FROM managed_tags WHERE product_id=? AND tag=?", (pid, hide_tag)
            )
        conn.commit()
        print(f"DONE — applied {len(to_hide)} hides, {len(to_unhide)} unhides")


if __name__ == "__main__":
    main()
