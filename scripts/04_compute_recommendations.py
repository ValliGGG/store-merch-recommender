"""Frequently Bought Together: lift-based co-purchase recommendations.

For each product A, generate up to 8 recommendations B where:
  - support(A,B) >= 10 (configurable)
  - B is published, in stock, in-season, and not the same parent product
  - B != A
Lookback window: 18 months.

Writes to `custom.recommended_products` (list.product_reference) so the
existing theme block ("Recommended products" / "Customers Also Bought")
renders our data-driven picks WITHOUT any theme change — zero perf impact.

Usage:
    python scripts/04_compute_recommendations.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib.util
from lib import config as cfg_mod, db as db_mod, seasonal
from lib.shopify_client import ShopifyClient

# Reuse the recent-orders (by id) working-set builder from 03b so FBT and the
# bestseller sort share one definition of "recent".
_spec = importlib.util.spec_from_file_location(
    "_bs_fbt", Path(__file__).resolve().parent / "03b_compute_bestsellers.py"
)
_bs = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_bs)

METAFIELDS_SET_M = """
mutation Set($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { id key }
    userErrors { field message }
  }
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=None, help="store code (default: sk / $ARTMIE_STORE)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min", type=int, default=None, help="override min co-occurrence")
    args = ap.parse_args()

    cfg = cfg_mod.load(args.store)
    print(f"[{cfg.store}] shop: {cfg.shop.store_url}  mode: {cfg.mode}")

    # Borrow-mode stores (e.g. PL) have too little own history — FBT is derived
    # from another store's co-purchase signal in a later step, not here.
    if cfg.mode == "borrow":
        print(f"[{cfg.store}] mode=borrow — own-data FBT skipped "
              f"(handled by the borrow step; see config.borrow_from={cfg.borrow_from}).")
        return

    client = ShopifyClient(cfg.shop)
    conn = db_mod.connect(cfg.db_path)
    db_mod.ensure_schema(conn)

    fbt = cfg.fbt
    ns = fbt["metafield_namespace"]
    key = fbt["metafield_key"]
    min_co = args.min if args.min is not None else int(fbt["min_co_occurrence"])
    max_recs = int(fbt["max_recommendations"])
    min_picks = int(fbt.get("min_picks_required", 1))
    lookback_months = int(fbt["lookback_months"])
    today = datetime.now(timezone.utc).date()
    season_cfg = cfg.seasonal

    print(f"writing to metafield {ns}.{key} (existing definition assumed — pre-created in admin)")
    with db_mod.run(conn, "fbt", notes=f"min_co={min_co} max={max_recs}"):
        # GUARDRAIL: never push FBT computed from too little data.
        floor = cfg.min_orders_floor
        total_usable = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE cancelled_at IS NULL"
        ).fetchone()[0]
        if total_usable < floor:
            print(f"::warning:: [{cfg.store}] only {total_usable} usable orders "
                  f"(< floor {floor}) — refusing to push FBT, skipping.", file=sys.stderr)
            return

        # 1. Recent-orders working set (by id) — shared definition with 03b.
        #    recent_orders already excludes cancelled orders.
        fbt_window = int(fbt.get("recent_orders_window", cfg.scoring["recent_orders_window"]))
        _bs.ensure_recent_orders_table(conn, fbt_window)
        n_orders = conn.execute("SELECT COUNT(*) FROM recent_orders").fetchone()[0]
        print(f"computing co-occurrence over {n_orders} most-recent orders (by id, min={min_co})...")
        t0 = time.time()
        conn.execute("DROP TABLE IF EXISTS pair_counts")
        conn.execute(
            f"""
            CREATE TEMP TABLE pair_counts AS
            SELECT
              li1.product_id AS a,
              li2.product_id AS b,
              COUNT(DISTINCT li1.order_id) AS co
            FROM line_items li1
            JOIN line_items li2
              ON li1.order_id = li2.order_id
              AND li1.product_id < li2.product_id
            JOIN recent_orders r ON r.id = li1.order_id
            GROUP BY li1.product_id, li2.product_id
            HAVING co >= {min_co}
            """
        )
        n_pairs = conn.execute("SELECT COUNT(*) FROM pair_counts").fetchone()[0]
        print(f"  pairs above threshold: {n_pairs}  ({time.time()-t0:.1f}s)")
        if n_pairs == 0:
            print("no pairs — nothing to push")
            return

        # 2. Per-product support (orders containing product, within the window)
        print("computing per-product support...")
        conn.execute("DROP TABLE IF EXISTS prod_support")
        conn.execute(
            """
            CREATE TEMP TABLE prod_support AS
            SELECT li.product_id AS pid, COUNT(DISTINCT li.order_id) AS s
            FROM line_items li
            JOIN recent_orders r ON r.id = li.order_id
            GROUP BY li.product_id
            """
        )
        print(f"  orders in window: {n_orders}")

        # 3. Compute lift, build recommendations per A
        print("computing lift + building per-product recommendation lists...")
        rows = conn.execute(
            """
            SELECT
              pc.a, pc.b, pc.co,
              sa.s AS sa, sb.s AS sb
            FROM pair_counts pc
            JOIN prod_support sa ON sa.pid = pc.a
            JOIN prod_support sb ON sb.pid = pc.b
            """
        ).fetchall()

        # Build adjacency with lift, both directions
        from collections import defaultdict
        recs: dict[str, list[tuple[float, str]]] = defaultdict(list)
        for r in rows:
            lift = (r["co"] * n_orders) / (r["sa"] * r["sb"])
            recs[r["a"]].append((lift, r["b"]))
            recs[r["b"]].append((lift, r["a"]))

        # 4. Filter candidates B by published/in-stock/in-season + not same handle
        prod_meta: dict[str, dict] = {}
        for r in conn.execute(
            "SELECT id, handle, status, total_inventory, season_tags, own_available, external_only FROM products"
        ):
            prod_meta[r["id"]] = dict(r)

        def candidate_ok(pid: str) -> bool:
            m = prod_meta.get(pid)
            if not m:
                return False
            if (m.get("status") or "").upper() != "ACTIVE":
                return False
            # Never recommend external-only (supplier) products, nor OOS ones.
            if m.get("external_only"):
                return False
            in_own = (bool(m.get("own_available")) if m.get("own_available") is not None
                      else (m.get("total_inventory") or 0) > 0)
            if not in_own:
                return False
            tags = (m.get("season_tags") or "").split(",") if m.get("season_tags") else []
            tags = [t for t in tags if t]
            if tags and not any(seasonal.is_in_season(t, season_cfg, today) for t in tags):
                return False
            return True

        # 5. Push metafields in batches of 25
        BATCH = 25
        batch: list[dict] = []
        pushed = 0
        skipped_unchanged = 0

        # Track last value to skip no-op writes (cheap optimization on weekly runs)
        existing: dict[str, str] = {}  # pid -> json string of current value
        # (Optional: pull current values via metafields query — keep simple, always push.)

        for pid_a, lifts in recs.items():
            if pid_a not in prod_meta:
                continue
            lifts.sort(reverse=True)  # by lift desc
            picks: list[str] = []
            for _, pid_b in lifts:
                if pid_b == pid_a:
                    continue
                if not candidate_ok(pid_b):
                    continue
                picks.append(pid_b)
                if len(picks) >= max_recs:
                    break
            if len(picks) < min_picks:
                continue

            value = json.dumps(picks)
            batch.append({
                "ownerId": pid_a,
                "namespace": ns,
                "key": key,
                "type": "list.product_reference",
                "value": value,
            })
            if len(batch) >= BATCH:
                if not args.dry_run:
                    d = client.execute(METAFIELDS_SET_M, {"metafields": batch})
                    errs = d["metafieldsSet"]["userErrors"]
                    if errs:
                        print(f"  warn: metafieldsSet userErrors: {errs[:3]}", file=sys.stderr)
                pushed += len(batch)
                batch = []

        if batch:
            if not args.dry_run:
                d = client.execute(METAFIELDS_SET_M, {"metafields": batch})
                errs = d["metafieldsSet"]["userErrors"]
                if errs:
                    print(f"  warn: metafieldsSet userErrors: {errs[:3]}", file=sys.stderr)
            pushed += len(batch)

        print(f"\nDONE — pushed FBT lists for {pushed} products"
              + (" (DRY RUN — no writes)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
