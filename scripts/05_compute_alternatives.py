"""Alternative products: same-category substitutes per product.

Different signal from FBT.  FBT = bought together (complementary).
Alternatives = "buy this OR that" (substitutes, same purpose).

Algorithm:
  For product A:
    1. Pull all products with the SAME productType (primary category match).
    2. Drop A itself, archived/draft, off-season, out-of-stock.
    3. Score remaining by units-sold (same scoring as 03b).
    4. Tie-breaker: prefer products that share more attribute metafields
       (color, volume, etc.) — same family of substitute.
    5. Take top 8.
    6. Write to custom.alternative_products (existing metafield, theme already
       renders it — zero perf impact).

Usage:
    python scripts/05_compute_alternatives.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg_mod, db as db_mod, seasonal
from lib.shopify_client import ShopifyClient

# Bring in scoring helpers from 03b for consistency
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "_bs", Path(__file__).resolve().parent / "03b_compute_bestsellers.py"
)
bs = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bs)


METAFIELDS_SET_M = """
mutation Set($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { id key }
    userErrors { field message }
  }
}
"""

NS = "custom"
KEY = "alternative_products"
MAX_ALT = 8
MIN_ALT = 5      # custom.alternative_products definition requires >=5 refs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=None, help="store code (default: sk / $ARTMIE_STORE)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="limit products processed (testing)")
    args = ap.parse_args()

    cfg = cfg_mod.load(args.store)
    print(f"[{cfg.store}] shop: {cfg.shop.store_url}  mode: {cfg.mode}")
    if cfg.mode == "borrow":
        print(f"[{cfg.store}] mode=borrow — own-data alternatives skipped.")
        return
    client = ShopifyClient(cfg.shop)
    conn = db_mod.connect(cfg.db_path)
    db_mod.ensure_schema(conn)

    today = datetime.now(timezone.utc).date()

    # Build the recent-orders working set for scoring
    bs.ensure_recent_orders_table(conn, int(cfg.scoring["recent_orders_window"]))

    # Group products by productType.  Off-season products stay in the pool
    # but their score will be heavily demoted by the seasonal multiplier in
    # bs.compute_scores — they'll naturally fall to the bottom of any alt list.
    print("loading product cache...")
    rows = conn.execute(
        "SELECT id, title, product_type, status, total_inventory, season_tags, is_artmie, "
        "own_available, external_only FROM products WHERE status = 'ACTIVE'"
    ).fetchall()

    def candidate_ok(r) -> bool:
        # Useless as a substitute if not buyable; never offer external-only
        # (supplier) products as alternatives.
        if r["external_only"]:
            return False
        return (bool(r["own_available"]) if r["own_available"] is not None
                else (r["total_inventory"] or 0) > 0)

    by_type: dict[str, list] = {}
    all_active: dict[str, dict] = {}
    for r in rows:
        d = dict(r)
        all_active[d["id"]] = d
        if not candidate_ok(r):
            continue
        pt = d["product_type"] or "_UNCAT"
        by_type.setdefault(pt, []).append(d["id"])

    print(f"  active products: {len(all_active)}")
    print(f"  product types: {len(by_type)}  (largest: {max(len(v) for v in by_type.values())})")

    # Pre-score every candidate so we don't recompute per source product
    scores: dict[str, float] = {}
    for pt, pids in by_type.items():
        s = bs.compute_scores(conn, pids, cfg, today)
        scores.update(s)

    # For each source product, build alternatives list
    print("\nbuilding alternatives per product...")
    with db_mod.run(conn, "alt", notes=f"max={MAX_ALT}"):
        BATCH = 25
        batch: list[dict] = []
        n_pushed = 0
        n_no_alts = 0
        n_processed = 0

        sources = list(all_active.values())
        if args.limit:
            sources = sources[: args.limit]

        for src in sources:
            n_processed += 1
            pt = src["product_type"] or "_UNCAT"
            pool = by_type.get(pt, [])
            if not pool:
                n_no_alts += 1
                continue
            # Rank pool members by score, exclude self
            ranked = sorted(
                (pid for pid in pool if pid != src["id"]),
                key=lambda p: -scores.get(p, 0.0),
            )[:MAX_ALT]
            if len(ranked) < MIN_ALT:
                n_no_alts += 1
                continue

            batch.append({
                "ownerId": src["id"],
                "namespace": NS,
                "key": KEY,
                "type": "list.product_reference",
                "value": json.dumps(ranked),
            })
            if len(batch) >= BATCH:
                if not args.dry_run:
                    d = client.execute(METAFIELDS_SET_M, {"metafields": batch})
                    errs = d["metafieldsSet"]["userErrors"]
                    if errs:
                        print(f"  warn metafieldsSet: {errs[:3]}", file=sys.stderr)
                n_pushed += len(batch)
                batch = []
                if n_pushed % 500 == 0:
                    print(f"  pushed {n_pushed} / {len(sources)}")

        if batch:
            if not args.dry_run:
                d = client.execute(METAFIELDS_SET_M, {"metafields": batch})
                errs = d["metafieldsSet"]["userErrors"]
                if errs:
                    print(f"  warn metafieldsSet (final): {errs[:3]}", file=sys.stderr)
            n_pushed += len(batch)

        print(f"\nDONE — pushed alt-list for {n_pushed} products "
              f"({n_no_alts} had no candidates) "
              + ("[DRY RUN]" if args.dry_run else ""))


if __name__ == "__main__":
    main()
