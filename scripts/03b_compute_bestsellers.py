"""Score every product, sort each collection, pin Artmie products.

Per spec §4.5:
  1. Pull all products in a collection (paginated)
  2. Filter out: archived, draft, off-season
  3. Compute score (recency-weighted units sold)
  4. Sort desc
  5. If no Artmie product is in slots 0..2, force the highest-scoring
     Artmie product into slot 2 (the 3rd position)
  6. collectionUpdate sortOrder=MANUAL (idempotent)
  7. collectionReorderProducts in chunks
  8. Wait for the returned job to complete

Bulk operations CAN'T do mutations, so we issue normal mutations per-collection.
At ~250 collections, this stays well under the rate limit.

Usage:
    python scripts/03b_compute_bestsellers.py [--dry-run] [--collection HANDLE]
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg_mod, db as db_mod, scoring, seasonal
from lib.shopify_client import ShopifyClient

LIST_COLLECTIONS_Q = """
query Collections($cursor: String) {
  collections(first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        handle
        title
        sortOrder
      }
    }
  }
}
"""

COLLECTION_PRODUCTS_Q = """
query CollectionProducts($id: ID!, $cursor: String) {
  collection(id: $id) {
    id
    handle
    title
    products(first: 250, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges {
        node {
          id
          status
        }
      }
    }
  }
}
"""

UPDATE_SORT_M = """
mutation UpdateSort($id: ID!) {
  collectionUpdate(input: { id: $id, sortOrder: MANUAL }) {
    collection { id sortOrder }
    userErrors { field message }
  }
}
"""

REORDER_M = """
mutation Reorder($id: ID!, $moves: [MoveInput!]!) {
  collectionReorderProducts(id: $id, moves: $moves) {
    job { id done }
    userErrors { field message }
  }
}
"""

JOB_Q = """
query Job($id: ID!) {
  job(id: $id) { id done }
}
"""


def seasonal_multiplier(product_row, season_cfg, today, *, in_season_boost: float, off_season_multiplier: float) -> float:
    """Return scoring multiplier based on today's seasonal state.

    - 1.0  if no season tags (non-seasonal product, normal scoring)
    - in_season_boost (e.g. 1.5) if at least one season tag is currently in-season
    - off_season_multiplier (e.g. 0.05) if all season tags are out-of-season
    """
    season_tags = (product_row["season_tags"] or "").split(",") if product_row["season_tags"] else []
    season_tags = [t for t in season_tags if t]
    if not season_tags:
        return 1.0
    if any(seasonal.is_in_season(t, season_cfg, today) for t in season_tags):
        return float(in_season_boost)
    return float(off_season_multiplier)


def fetch_collection_product_ids(client, coll_id: str) -> list[str]:
    out = []
    cursor = None
    while True:
        d = client.execute(COLLECTION_PRODUCTS_Q, {"id": coll_id, "cursor": cursor})
        coll = d["collection"]
        if not coll:
            return out
        for e in coll["products"]["edges"]:
            out.append(e["node"]["id"])
        pi = coll["products"]["pageInfo"]
        if not pi["hasNextPage"]:
            break
        cursor = pi["endCursor"]
    return out


def ensure_recent_orders_table(conn, window_size: int) -> None:
    """Build a TEMP table of the N most-recent orders by numeric id.

    Computed once per script run — every collection scoring query joins it.
    """
    conn.execute("DROP TABLE IF EXISTS recent_orders")
    conn.execute(
        f"""
        CREATE TEMP TABLE recent_orders AS
        SELECT id FROM orders
        WHERE cancelled_at IS NULL
        ORDER BY CAST(SUBSTR(id, INSTR(id,'/Order/')+7) AS INTEGER) DESC
        LIMIT {int(window_size)}
        """
    )
    conn.execute("CREATE INDEX idx_recent_orders_id ON recent_orders(id)")


def compute_scores(conn, product_ids: list[str], cfg, today) -> dict[str, float]:
    """Score = units * sale_boost * seasonal_multiplier, plus cold-start bonus.

    Multipliers stack:
      - sale_boost: 1 + discount_pct * coefficient   (boost on-sale items)
      - seasonal:   1.5 in-season, 0.05 off-season, 1.0 non-seasonal
    """
    if not product_ids:
        return {}
    placeholders = ",".join("?" * len(product_ids))
    rows = conn.execute(
        f"""
        SELECT li.product_id AS pid,
               SUM(MAX(li.quantity - li.refunded_quantity, 0)) AS units
        FROM line_items li
        JOIN recent_orders r ON r.id = li.order_id
        WHERE li.product_id IN ({placeholders})
        GROUP BY li.product_id
        """,
        product_ids,
    ).fetchall()
    raw_units: dict[str, float] = {r["pid"]: float(r["units"] or 0) for r in rows}

    weights = cfg.scoring
    sale_coef = float(weights.get("sale_boost_coefficient", 0.0))
    in_season_boost = float(weights.get("in_season_boost", 1.0))
    off_season_mult = float(weights.get("off_season_multiplier", 1.0))
    oos_mult = float(weights.get("out_of_stock_multiplier", 0.0))
    season_cfg = cfg.seasonal

    score_by_pid: dict[str, float] = {}
    inventory_by_pid: dict[str, int] = {}
    for row in conn.execute(
        f"SELECT id, discount_pct, created_at, season_tags, total_inventory FROM products WHERE id IN ({placeholders})",
        product_ids,
    ):
        units = raw_units.get(row["id"], 0.0)
        disc = float(row["discount_pct"] or 0.0)
        sale_mult = 1.0 + disc * sale_coef
        season_mult = seasonal_multiplier(
            row, season_cfg, today,
            in_season_boost=in_season_boost,
            off_season_multiplier=off_season_mult,
        )
        score_by_pid[row["id"]] = units * sale_mult * season_mult
        inventory_by_pid[row["id"]] = int(row["total_inventory"] or 0)

    # Cold-start bonus capped relative to top organic score (no seasonal modifier on bonus)
    top_score = max(score_by_pid.values(), default=0.0)
    cap = top_score * float(weights.get("cold_start_max_score_pct", 0.25))
    for row in conn.execute(
        f"SELECT id, created_at FROM products WHERE id IN ({placeholders})", product_ids
    ):
        bonus = scoring.cold_start_bonus(row["created_at"], weights)
        if bonus:
            score_by_pid[row["id"]] = score_by_pid.get(row["id"], 0.0) + min(bonus, cap)

    # Out-of-stock multiplier applied LAST so it dominates everything else
    # (including cold-start bonus). 0.0 means OOS products always score 0
    # and sort to the absolute bottom of the collection.
    for pid in product_ids:
        score_by_pid.setdefault(pid, 0.0)
        if inventory_by_pid.get(pid, 0) <= 0:
            score_by_pid[pid] *= oos_mult
    return score_by_pid


def _in_stock(product_meta: dict, pid: str) -> bool:
    """In OWN stock — external-only and OOS products are NOT 'in stock' here, so
    pins never promote them."""
    m = product_meta.get(pid, {})
    if "own_available" in m and m.get("own_available") is not None:
        return bool(m.get("own_available"))
    return (m.get("total_inventory") or 0) > 0   # fallback for pre-migration caches


def stock_tier(product_meta: dict, pid: str) -> int:
    """0 = own stock, 1 = external/supplier only, 2 = out of stock. Lower ranks first."""
    m = product_meta.get(pid, {})
    if m.get("own_available"):
        return 0
    if m.get("external_only"):
        return 1
    if (m.get("total_inventory") or 0) > 0 and "own_available" not in m:
        return 0   # pre-migration fallback: treat any inventory as own
    return 2


def apply_sale_pin(ranked_pids: list[str], product_meta: dict, pin_pos: int, min_disc: float) -> list[str]:
    """Promote the top in-stock sale item into slot pin_pos.
    Out-of-stock candidates are never pinned.
    """
    if not ranked_pids:
        return ranked_pids
    on_sale = [pid for pid in ranked_pids
               if _in_stock(product_meta, pid)
               and (product_meta.get(pid, {}).get("discount_pct") or 0) >= min_disc]
    if not on_sale:
        return ranked_pids
    head = ranked_pids[: pin_pos + 1]
    if any(_in_stock(product_meta, pid)
           and (product_meta.get(pid, {}).get("discount_pct") or 0) >= min_disc
           for pid in head):
        return ranked_pids
    promoted = on_sale[0]
    new_order = [pid for pid in ranked_pids if pid != promoted]
    new_order.insert(pin_pos, promoted)
    return new_order


def apply_artmie_pin(ranked_pids: list[str], product_meta: dict, pin_pos: int) -> list[str]:
    """If no in-stock Artmie product is in slots 0..pin_pos, promote the top in-stock Artmie product."""
    head = ranked_pids[: pin_pos + 1]
    if any(product_meta.get(pid, {}).get("is_artmie") and _in_stock(product_meta, pid) for pid in head):
        return ranked_pids
    artmie_in_list = [pid for pid in ranked_pids
                      if product_meta.get(pid, {}).get("is_artmie")
                      and _in_stock(product_meta, pid)]
    if not artmie_in_list:
        return ranked_pids
    promoted = artmie_in_list[0]
    new_order = [pid for pid in ranked_pids if pid != promoted]
    new_order.insert(pin_pos, promoted)
    return new_order


def wait_job(client, job_id: str, *, timeout_s: int = 600) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        d = client.execute(JOB_Q, {"id": job_id})
        if d["job"]["done"]:
            return True
        time.sleep(2)
    return False


def reorder_collection(client, coll_id: str, ordered_pids: list[str], *, dry_run: bool):
    # Build moves payload
    moves = [{"id": pid, "newPosition": str(i)} for i, pid in enumerate(ordered_pids)]
    if dry_run:
        return
    # Set manual sort (idempotent)
    d = client.execute(UPDATE_SORT_M, {"id": coll_id})
    errs = d["collectionUpdate"]["userErrors"]
    if errs:
        raise RuntimeError(f"sort update errors: {errs}")
    # Reorder in chunks of 250 (mutation accepts the full list, but stay conservative)
    CHUNK = 250
    for i in range(0, len(moves), CHUNK):
        slice_ = moves[i : i + CHUNK]
        d = client.execute(REORDER_M, {"id": coll_id, "moves": slice_})
        errs = d["collectionReorderProducts"]["userErrors"]
        if errs:
            raise RuntimeError(f"reorder errors: {errs}")
        job = d["collectionReorderProducts"]["job"]
        if job and not wait_job(client, job["id"]):
            raise RuntimeError(f"reorder job timeout: {job['id']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=None, help="store code (default: sk / $ARTMIE_STORE)")
    ap.add_argument("--dry-run", action="store_true", help="compute but don't push")
    ap.add_argument("--collection", help="run only for this collection handle")
    ap.add_argument("--limit", type=int, default=0, help="limit number of collections processed")
    args = ap.parse_args()

    cfg = cfg_mod.load(args.store)
    print(f"[{cfg.store}] shop: {cfg.shop.store_url}  mode: {cfg.mode}")

    # Borrow-mode stores (e.g. PL) have too little own history to score from —
    # their ordering is derived from another store's signal in a later step.
    # Refuse to touch their collections here (no own-data sort).
    if cfg.mode == "borrow":
        print(f"[{cfg.store}] mode=borrow — own-data sort skipped "
              f"(handled by the borrow step; see config.borrow_from={cfg.borrow_from}).")
        return

    client = ShopifyClient(cfg.shop)
    conn = db_mod.connect(cfg.db_path)
    db_mod.ensure_schema(conn)

    today = datetime.now(timezone.utc).date()

    with db_mod.run(conn, "sort", notes=("dry-run " if args.dry_run else "") + (args.collection or "all")):
        # Build the recent-orders working set ONCE per run (used by every collection)
        window = int(cfg.scoring["recent_orders_window"])
        ensure_recent_orders_table(conn, window)
        n_recent = conn.execute("SELECT COUNT(*) FROM recent_orders").fetchone()[0]
        print(f"scoring window: {n_recent} most-recent orders by id")

        # GUARDRAIL: never reorder from too little data — a bad/empty data day
        # would otherwise flatten every collection's merchandising.  Clean skip.
        floor = cfg.min_orders_floor
        if n_recent < floor:
            print(f"::warning:: [{cfg.store}] only {n_recent} usable orders "
                  f"(< floor {floor}) — refusing to reorder, skipping push.", file=sys.stderr)
            return

        # 1. List collections
        collections = []
        cursor = None
        while True:
            d = client.execute(LIST_COLLECTIONS_Q, {"cursor": cursor})
            for e in d["collections"]["edges"]:
                collections.append(e["node"])
            pi = d["collections"]["pageInfo"]
            if not pi["hasNextPage"]:
                break
            cursor = pi["endCursor"]
        print(f"found {len(collections)} collections")

        if args.collection:
            collections = [c for c in collections if c["handle"] == args.collection]
        if args.limit:
            collections = collections[: args.limit]

        # 2. Per collection
        pin_pos = int(cfg.artmie_brand["pin_position"])
        season_cfg = cfg.seasonal
        for ci, coll in enumerate(collections, 1):
            t_coll = time.time()
            pids = fetch_collection_product_ids(client, coll["id"])
            if not pids:
                print(f"[{ci}/{len(collections)}] {coll['handle']!r} — empty, skip")
                continue

            # Hydrate product meta from local cache
            placeholders = ",".join("?" * len(pids))
            rows = conn.execute(
                f"SELECT * FROM products WHERE id IN ({placeholders})", pids
            ).fetchall()
            meta: dict[str, dict] = {r["id"]: dict(r) for r in rows}

            # Filter — keep all active products (off-season demoted via score, not hidden)
            kept = [
                pid for pid in pids
                if pid in meta
                   and (meta[pid].get("status") or "").upper() == "ACTIVE"
            ]
            if not kept:
                print(f"[{ci}/{len(collections)}] {coll['handle']!r} — all filtered out")
                continue

            # Score + sort. Primary key is the stock tier (own > external-only >
            # OOS) so an external-only product can never outrank an own-stock one;
            # score orders within each tier.
            scores = compute_scores(conn, kept, cfg, today)
            ranked = sorted(
                kept,
                key=lambda p: (stock_tier(meta, p), -scores.get(p, 0.0), meta[p].get("title") or ""),
            )
            # Pin order matters: sale pin first (slot 1), then Artmie pin (slot 2/3 falls
            # to whatever the artmie pin position is — the pin only triggers if no Artmie
            # product is in slots 0..pin_pos AFTER the sale pin has run).
            with_sale = apply_sale_pin(
                ranked, meta,
                pin_pos=int(cfg.scoring.get("sale_pin_position", 1)),
                min_disc=float(cfg.scoring.get("sale_pin_min_discount", 0.05)),
            )
            with_pin = apply_artmie_pin(with_sale, meta, pin_pos)
            sale_pinned = (with_sale != ranked)
            artmie_pinned = (with_pin != with_sale)

            # Push
            try:
                reorder_collection(client, coll["id"], with_pin, dry_run=args.dry_run)
            except Exception as e:
                print(f"  ERROR reordering {coll['handle']!r}: {e}", file=sys.stderr)
                continue

            elapsed = time.time() - t_coll
            print(f"[{ci}/{len(collections)}] {coll['handle']!r}  "
                  f"products={len(kept)}  sale={'Y' if sale_pinned else 'n'}  "
                  f"artmie={'Y' if artmie_pinned else 'n'}  "
                  f"top3={[meta[p]['title'][:30] for p in with_pin[:3]]}  ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
