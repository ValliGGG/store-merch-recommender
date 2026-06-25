"""Borrow a data-rich store's demand signal and apply it to a low-data store.

Some stores have too little order history to score from, but their catalog
mirrors a data-rich store (nearly all products share a primary-variant SKU with
a product in the source store). So we:

  1. Read the SOURCE store's order history (its local SQLite cache) to compute
     per-product units sold + lift-based co-purchase recommendations.
  2. Map source product -> SKU (live) so the signal is keyed by SKU.
  3. For the TARGET store, map SKU -> target product (live), then:
       - sort each collection by the borrowed units (OOS to the bottom, Artmie
         pinned to slot 3), and
       - write the borrowed FBT picks to custom.recommended_products.

Self-contained: needs the SOURCE store's SQLite cache (orders_<source>.db) plus
BOTH stores' tokens in the environment. Reuses 03b's reorder/pin helpers.

Per-collection COVERAGE GUARD: if too few of a collection's products map to a
source SKU, that collection is left untouched (it would otherwise be scrambled).

Usage:
    python scripts/09_borrow_recommendations.py --target pl [--source sk]
                                                [--dry-run] [--collection H] [--limit N]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg_mod, db as db_mod
from lib.shopify_client import ShopifyClient

# Reuse the bestseller helpers (recent-orders window, reorder, pins, mutations).
_spec = importlib.util.spec_from_file_location(
    "_bs_borrow", Path(__file__).resolve().parent / "03b_compute_bestsellers.py"
)
_bs = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_bs)

# Minimum fraction of a collection's products that must map to a source SKU
# before we dare reorder it. Below this we leave the collection as-is.
MIN_COVERAGE = 0.30

# Lean queries — fetch only what each side needs (the full catalog is large, so
# pulling metafields(first:30) per product would exhaust memory).
SRC_Q = """
query($cursor:String){
  products(first:250, after:$cursor){
    pageInfo{ hasNextPage endCursor }
    edges{ node{ id variants(first:1){ edges{ node{ sku } } } } }
  }
}
"""

TGT_Q = """
query($cursor:String){
  products(first:250, after:$cursor){
    pageInfo{ hasNextPage endCursor }
    edges{ node{
      id status totalInventory
      variants(first:1){ edges{ node{ sku } } }
      znacka: metafield(namespace:"custom", key:"znacka"){ value }
    } }
  }
}
"""

METAFIELDS_SET_M = """
mutation Set($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { id key }
    userErrors { field message }
  }
}
"""


def _primary_sku(node: dict) -> str | None:
    vs = node.get("variants", {}).get("edges") or []
    if vs and vs[0]["node"].get("sku"):
        return vs[0]["node"]["sku"].strip()
    return None


def fetch_source_skus(client) -> dict[str, str | None]:
    """Source needs only product GID -> primary SKU."""
    out: dict[str, str | None] = {}
    cursor = None
    while True:
        d = client.execute(SRC_Q, {"cursor": cursor})
        for e in d["products"]["edges"]:
            n = e["node"]
            out[n["id"]] = _primary_sku(n)
        pi = d["products"]["pageInfo"]
        if not pi["hasNextPage"]:
            break
        cursor = pi["endCursor"]
    return out


def fetch_target_meta(client, artmie_values: set[str]) -> dict[str, dict]:
    """Target -> {sku, status, inventory, is_artmie} keyed by GID."""
    out: dict[str, dict] = {}
    cursor = None
    while True:
        d = client.execute(TGT_Q, {"cursor": cursor})
        for e in d["products"]["edges"]:
            n = e["node"]
            znacka = ((n.get("znacka") or {}).get("value") or "").strip()
            out[n["id"]] = {
                "sku": _primary_sku(n),
                "status": n.get("status"),
                "inventory": int(n.get("totalInventory") or 0),
                "is_artmie": znacka in artmie_values,
            }
        pi = d["products"]["pageInfo"]
        if not pi["hasNextPage"]:
            break
        cursor = pi["endCursor"]
    return out


def source_units_by_pid(conn, window: int) -> dict[str, float]:
    _bs.ensure_recent_orders_table(conn, window)
    rows = conn.execute(
        """
        SELECT li.product_id AS pid,
               SUM(MAX(li.quantity - li.refunded_quantity, 0)) AS units
        FROM line_items li
        JOIN recent_orders r ON r.id = li.order_id
        GROUP BY li.product_id
        """
    ).fetchall()
    return {r["pid"]: float(r["units"] or 0) for r in rows}


def source_fbt_by_pid(conn, *, min_co: int, max_recs: int) -> dict[str, list[str]]:
    """Lift-based co-purchase picks per source product id (over recent_orders)."""
    conn.execute("DROP TABLE IF EXISTS b_pairs")
    conn.execute(
        f"""
        CREATE TEMP TABLE b_pairs AS
        SELECT li1.product_id AS a, li2.product_id AS b, COUNT(DISTINCT li1.order_id) AS co
        FROM line_items li1
        JOIN line_items li2 ON li1.order_id = li2.order_id AND li1.product_id < li2.product_id
        JOIN recent_orders r ON r.id = li1.order_id
        GROUP BY li1.product_id, li2.product_id
        HAVING co >= {int(min_co)}
        """
    )
    conn.execute("DROP TABLE IF EXISTS b_support")
    conn.execute(
        """
        CREATE TEMP TABLE b_support AS
        SELECT li.product_id AS pid, COUNT(DISTINCT li.order_id) AS s
        FROM line_items li JOIN recent_orders r ON r.id = li.order_id
        GROUP BY li.product_id
        """
    )
    n_orders = conn.execute("SELECT COUNT(*) FROM recent_orders").fetchone()[0] or 1
    from collections import defaultdict
    recs: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for r in conn.execute(
        "SELECT p.a, p.b, p.co, sa.s AS sa, sb.s AS sb FROM b_pairs p "
        "JOIN b_support sa ON sa.pid=p.a JOIN b_support sb ON sb.pid=p.b"
    ):
        lift = (r["co"] * n_orders) / (r["sa"] * r["sb"])
        recs[r["a"]].append((lift, r["b"]))
        recs[r["b"]].append((lift, r["a"]))
    out: dict[str, list[str]] = {}
    for pid, lifts in recs.items():
        lifts.sort(reverse=True)
        out[pid] = [b for _, b in lifts[: max_recs * 2]]  # extra headroom for target filtering
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="store code to apply the signal to (e.g. pl)")
    ap.add_argument("--source", default=None, help="store providing the signal (default: target's borrow_from, else sk)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--collection", help="run only for this target collection handle")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    target_cfg = cfg_mod.load(args.target)
    source_code = args.source or target_cfg.borrow_from or "sk"
    source_cfg = cfg_mod.load(source_code)

    print(f"borrow: source={source_cfg.store} ({source_cfg.shop.store_url}) "
          f"-> target={target_cfg.store} ({target_cfg.shop.store_url})"
          + ("  [dry-run]" if args.dry_run else ""))

    # Source signal requires the source store's local order cache.
    if not source_cfg.db_path.exists():
        print(f"::error:: source cache {source_cfg.db_path} not found — run the "
              f"{source_cfg.store} pipeline first.", file=sys.stderr)
        sys.exit(2)

    conn = db_mod.connect(source_cfg.db_path)
    window = int(source_cfg.scoring["recent_orders_window"])
    units_by_pid = source_units_by_pid(conn, window)

    # GUARDRAIL: don't borrow from an empty/too-thin source.
    n_recent = conn.execute("SELECT COUNT(*) FROM recent_orders").fetchone()[0]
    if n_recent < int(source_cfg.min_orders_floor):
        print(f"::warning:: source {source_cfg.store} has only {n_recent} orders "
              f"(< floor {source_cfg.min_orders_floor}) — refusing to borrow.", file=sys.stderr)
        return

    fbt = source_cfg.fbt
    fbt_picks_by_pid = source_fbt_by_pid(
        conn, min_co=int(fbt["min_co_occurrence"]), max_recs=int(fbt["max_recommendations"])
    )

    # Artmie brand value-set (for the target pin), from the shared selectors.
    artmie_values = {
        s["equals"] for s in target_cfg.artmie_brand["selectors"]
        if s.get("type") == "metafield" and s.get("key") == "znacka" and s.get("equals")
    }

    # --- map source pid -> sku (live) ---
    src_client = ShopifyClient(source_cfg.shop)
    print("fetching source product->sku map...")
    pid_to_sku = fetch_source_skus(src_client)
    sku_units: dict[str, float] = {}
    sku_picks_src_pids: dict[str, list[str]] = {}
    for pid, sku in pid_to_sku.items():
        if not sku:
            continue
        if pid in units_by_pid:
            sku_units[sku] = sku_units.get(sku, 0.0) + units_by_pid[pid]
        if pid in fbt_picks_by_pid:
            picks_skus = [pid_to_sku.get(p) for p in fbt_picks_by_pid[pid]]
            sku_picks_src_pids[sku] = [s for s in picks_skus if s]

    print(f"  source: {len(pid_to_sku)} products, {len(sku_units)} SKUs with sales, "
          f"{len(sku_picks_src_pids)} SKUs with FBT picks")

    # --- map target sku -> target product (live) ---
    tgt_client = ShopifyClient(target_cfg.shop)
    print("fetching target product->sku map...")
    tgt_products = fetch_target_meta(tgt_client, artmie_values)
    sku_to_tgt_pid: dict[str, str] = {}
    for pid, m in tgt_products.items():
        if m["sku"]:
            sku_to_tgt_pid.setdefault(m["sku"], pid)

    # Set of ALL source SKUs — used by the per-collection coverage guard (can we
    # map a product to the source at all?), distinct from "has sales".
    src_sku_set = {s for s in pid_to_sku.values() if s}
    overlap = sum(1 for pid, m in tgt_products.items() if m["sku"] in sku_units)
    print(f"  target: {len(tgt_products)} products; {overlap} map to a source SKU with sales")

    pin_pos = int(target_cfg.artmie_brand["pin_position"])

    # =====================================================================
    # 1) Borrowed collection sort
    # =====================================================================
    print("\n[sort] reordering target collections by borrowed demand...")
    collections = []
    cursor = None
    while True:
        d = tgt_client.execute(_bs.LIST_COLLECTIONS_Q, {"cursor": cursor})
        for e in d["collections"]["edges"]:
            collections.append(e["node"])
        pi = d["collections"]["pageInfo"]
        if not pi["hasNextPage"]:
            break
        cursor = pi["endCursor"]
    if args.collection:
        collections = [c for c in collections if c["handle"] == args.collection]
    if args.limit:
        collections = collections[: args.limit]

    reordered = skipped_cov = 0
    for ci, coll in enumerate(collections, 1):
        pids = _bs.fetch_collection_product_ids(tgt_client, coll["id"])
        active = [p for p in pids if (tgt_products.get(p, {}).get("status") or "").upper() == "ACTIVE"]
        if not active:
            continue
        # Coverage = fraction of products that exist in the SOURCE catalog by
        # SKU (i.e. can be mapped at all). Low coverage => leave untouched rather
        # than scramble a collection we can't meaningfully rank.
        mapped = [p for p in active if tgt_products[p]["sku"] in src_sku_set]
        coverage = len(mapped) / len(active)
        if coverage < MIN_COVERAGE:
            skipped_cov += 1
            print(f"[{ci}/{len(collections)}] {coll['handle']!r} — coverage {coverage:.0%} < "
                  f"{MIN_COVERAGE:.0%}, left untouched")
            continue

        def score(pid):
            m = tgt_products[pid]
            base = sku_units.get(m["sku"] or "", 0.0)
            if m["inventory"] <= 0:
                return -1.0  # OOS always below any in-stock (incl zero-sales) product
            return base

        # Stable tiebreak on CURRENT position: products with no source signal
        # keep their existing relative order; only signal-bearing items are
        # lifted and OOS items dropped to the bottom.
        pos = {pid: i for i, pid in enumerate(active)}
        ranked = sorted(active, key=lambda p: (-score(p), pos[p]))
        ranked = _bs.apply_artmie_pin(
            ranked,
            {p: {"is_artmie": tgt_products[p]["is_artmie"],
                 "total_inventory": tgt_products[p]["inventory"]} for p in ranked},
            pin_pos,
        )
        try:
            _bs.reorder_collection(tgt_client, coll["id"], ranked, dry_run=args.dry_run)
            reordered += 1
            if ci <= 8 or ci % 25 == 0:
                print(f"[{ci}/{len(collections)}] {coll['handle']!r} cov={coverage:.0%} "
                      f"n={len(active)} reordered")
        except Exception as e:
            print(f"  ERROR reorder {coll['handle']!r}: {e}", file=sys.stderr)

    print(f"[sort] {reordered} collections reordered, {skipped_cov} skipped (low coverage)"
          + (" [dry-run]" if args.dry_run else ""))

    # =====================================================================
    # 2) Borrowed FBT -> custom.recommended_products on target
    # =====================================================================
    ns = fbt["metafield_namespace"]; key = fbt["metafield_key"]
    min_picks = int(fbt.get("min_picks_required", 1)); max_recs = int(fbt["max_recommendations"])
    print(f"\n[fbt] writing borrowed picks to {ns}.{key} on target...")
    batch: list[dict] = []
    pushed = 0
    BATCH = 25
    for pid, m in tgt_products.items():
        if (m.get("status") or "").upper() != "ACTIVE":
            continue
        sku = m["sku"]
        if not sku or sku not in sku_picks_src_pids:
            continue
        # translate source pick SKUs -> target pids that exist + are in stock
        picks = []
        for pick_sku in sku_picks_src_pids[sku]:
            tp = sku_to_tgt_pid.get(pick_sku)
            if tp and tp != pid and tgt_products.get(tp, {}).get("inventory", 0) > 0:
                picks.append(tp)
            if len(picks) >= max_recs:
                break
        if len(picks) < min_picks:
            continue
        batch.append({"ownerId": pid, "namespace": ns, "key": key,
                      "type": "list.product_reference", "value": json.dumps(picks)})
        if len(batch) >= BATCH:
            if not args.dry_run:
                d = tgt_client.execute(METAFIELDS_SET_M, {"metafields": batch})
                errs = d["metafieldsSet"]["userErrors"]
                if errs:
                    print(f"  warn metafieldsSet: {errs[:2]}", file=sys.stderr)
            pushed += len(batch); batch = []
    if batch and not args.dry_run:
        d = tgt_client.execute(METAFIELDS_SET_M, {"metafields": batch})
        errs = d["metafieldsSet"]["userErrors"]
        if errs:
            print(f"  warn metafieldsSet: {errs[:2]}", file=sys.stderr)
    if batch:
        pushed += len(batch)
    print(f"[fbt] {'would push' if args.dry_run else 'pushed'} borrowed FBT for {pushed} target products")


if __name__ == "__main__":
    main()
