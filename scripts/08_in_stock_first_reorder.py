"""Reorder all menu parent collections so in-stock products come before OOS.

Why: SK's pipeline (03b) sorts EVERY collection with OOS-at-bottom logic, but
PL/BA/MK don't have order data so 03b can't run there. Result: their parent
collections still use Shopify's BEST_SELLING sort, which places OOS products
at top — exactly what users complained about on 2026-04-27.

This script provides a minimum-viable fix: per parent collection, set MANUAL
sort and reorder so all in-stock products come first (preserving their existing
relative order), then all OOS products in their existing relative order.

Idempotent. Runs in ~30 sec per parent collection (depends on size).

Usage:
    python scripts/08_in_stock_first_reorder.py --store pl
    python scripts/08_in_stock_first_reorder.py --store ba
    python scripts/08_in_stock_first_reorder.py --store mk
"""
from __future__ import annotations
import argparse, importlib.util, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig

# Reuse menu-parent resolver from 07
_spec = importlib.util.spec_from_file_location("s7", Path(__file__).resolve().parent / "07_sync_parent_collections.py")
s7 = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(s7)


COLL_PRODUCTS_Q = """
query ($id: ID!, $cursor: String) {
  collection(id: $id) {
    products(first: 250, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node { id totalInventory } }
    }
  }
}
"""

UPDATE_SORT_M = """
mutation ($id: ID!) {
  collectionUpdate(input: { id:$id, sortOrder: MANUAL }) {
    collection { id sortOrder }
    userErrors { field message }
  }
}
"""

REORDER_M = """
mutation ($id: ID!, $moves: [MoveInput!]!) {
  collectionReorderProducts(id: $id, moves: $moves) {
    job { id done }
    userErrors { field message }
  }
}
"""

JOB_Q = "query ($id:ID!){ job(id:$id) { id done } }"


def wait_job(client, job_id: str, timeout_s: int = 300) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if client.execute(JOB_Q, {"id": job_id})["job"]["done"]:
            return True
        time.sleep(2)
    return False


def fetch_products_with_inventory(client, coll_gid: str) -> list[tuple[str, int]]:
    """Return [(product_gid, total_inventory), ...] in current collection order."""
    out = []
    cursor = None
    while True:
        d = client.execute(COLL_PRODUCTS_Q, {"id": coll_gid, "cursor": cursor})
        coll = d["collection"]
        if not coll: return out
        for e in coll["products"]["edges"]:
            out.append((e["node"]["id"], int(e["node"].get("totalInventory") or 0)))
        pi = coll["products"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]
    return out


def reorder_in_stock_first(client, coll_gid: str, dry_run: bool = False) -> tuple[int, int, int]:
    """Returns (n_total, n_in_stock, n_oos). Sets MANUAL sort + reorders."""
    pids_with_inv = fetch_products_with_inventory(client, coll_gid)
    if not pids_with_inv:
        return (0, 0, 0)
    in_stock = [pid for pid, inv in pids_with_inv if inv > 0]
    oos      = [pid for pid, inv in pids_with_inv if inv <= 0]
    desired_order = in_stock + oos
    current_order = [pid for pid, _ in pids_with_inv]
    if desired_order == current_order:
        return (len(pids_with_inv), len(in_stock), len(oos))   # no change needed

    if dry_run:
        return (len(pids_with_inv), len(in_stock), len(oos))

    # Set sort to MANUAL (idempotent)
    d = client.execute(UPDATE_SORT_M, {"id": coll_gid})
    errs = d["collectionUpdate"]["userErrors"]
    if errs: raise RuntimeError(f"sort update errors: {errs}")

    # Build moves and chunk into 250
    moves = [{"id": pid, "newPosition": str(i)} for i, pid in enumerate(desired_order)]
    CHUNK = 250
    for i in range(0, len(moves), CHUNK):
        slice_ = moves[i:i+CHUNK]
        d = client.execute(REORDER_M, {"id": coll_gid, "moves": slice_})
        errs = d["collectionReorderProducts"]["userErrors"]
        if errs: raise RuntimeError(f"reorder errors: {errs}")
        job = d["collectionReorderProducts"]["job"]
        if job and not wait_job(client, job["id"]):
            raise RuntimeError(f"reorder job timeout for {coll_gid}")
    return (len(pids_with_inv), len(in_stock), len(oos))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True,
                    choices=["sk","cz","pl","hu","ro","mk","rs","ba"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = cfg_mod.load(args.store)
    code = args.store.upper()
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    tok = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    if not url:
        print(f"ERROR: missing env for {code}", file=sys.stderr); sys.exit(2)
    shop = ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version)
    client = ShopifyClient(shop)
    print(f"store: {url}  mode: {'DRY-RUN' if args.dry_run else 'APPLY'}")

    # Get parent collections from menu
    d = client.execute(s7.MENU_Q)
    menus = {e["node"]["handle"]: e["node"] for e in d["menus"]["edges"]}
    menu = menus.get("artmie-menu") or menus.get("main-menu")
    if not menu:
        print("ERROR: no menu found"); sys.exit(2)
    parents = s7.get_parent_collections(menu, client)
    print(f"  parent collections: {len(parents)}")

    total_reordered = 0
    total_oos_demoted = 0
    for parent_item, _ in parents:
        gid = parent_item.get("_resolved_gid") or parent_item.get("resourceId")
        title = parent_item.get("title", "?")
        if not gid:
            print(f"  ! {title} no gid, skip"); continue
        try:
            n_total, n_in, n_oos = reorder_in_stock_first(client, gid, dry_run=args.dry_run)
            if n_oos > 0:
                total_oos_demoted += n_oos
                action = f"+{n_in} in-stock first, {n_oos} OOS demoted to bottom"
                if args.dry_run: action = f"would: {action}"
                print(f"  - {title[:35]:35s} total={n_total:4d}  {action}")
                total_reordered += 1
            else:
                pass  # silent for clean collections
        except Exception as e:
            print(f"  ! {title[:35]}: {e}")

    print(f"\nDONE — reordered {total_reordered} parent collections, demoted {total_oos_demoted} OOS products"
          + (" [dry-run]" if args.dry_run else ""))


if __name__ == "__main__":
    main()
