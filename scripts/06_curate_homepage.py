"""Maintain a 12-product 'homepage-curated' collection that mixes top sellers from
key categories (per user 2026-04-26):

  Slots 1-2:  bestsellers (from `bestsellery`)
  Slots 3-4:  paints      (from `umelecke-farby`)
  Slots 5-6:  brushes     (from `umelecke-stetce-a-pomocky`)
  Slot  7:    canvas      (from `maliarske-platna`)
  Slots 8-9:  kids        (from `kreativne-potreby-pre-deti`)
  Slot  10:   paper       (from `papier-scrapbook-dekupaz`)
  Slots 11-12: Artmie / sale wildcards (any in-stock Artmie or sale-on product
                not already picked from the categories above)

All picks are in-stock only; they're chosen by the same scoring engine that
03b uses (units sold × sale_boost × seasonal × OOS multiplier).

Creates the collection if missing, idempotently updates contents and order
on each run.  Designed to run AFTER 02b (product cache fresh) and 03b (so we
can reuse the recent_orders table state implicitly via re-build).
"""
from __future__ import annotations
import argparse, importlib.util, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg_mod, db as db_mod
from lib.shopify_client import ShopifyClient

# Reuse 03b helpers
_spec = importlib.util.spec_from_file_location(
    "_bs", Path(__file__).resolve().parent / "03b_compute_bestsellers.py"
)
bs = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bs)


CURATED_HANDLE = "homepage-curated"
CURATED_TITLE  = "Odporúčame TOP PICKS"

# (collection_handle, count) in display order
CATEGORY_PICKS = [
    ("bestsellery",                   2),
    ("umelecke-farby",                2),
    ("umelecke-stetce-a-pomocky",     2),
    ("maliarske-platna",              1),
    ("kreativne-potreby-pre-deti",    2),
    ("papier-scrapbook-dekupaz",      1),
]
WILDCARD_COUNT = 2   # Artmie / sale fillers
TOTAL_PICKS = sum(n for _, n in CATEGORY_PICKS) + WILDCARD_COUNT  # = 12


# ---------------------------------------------------------------------------
# GraphQL
# ---------------------------------------------------------------------------

COLL_BY_HANDLE_Q = """
query ($h: String!) {
  collectionByHandle(handle: $h) { id title sortOrder }
}
"""

LIST_PRODUCTS_Q = """
query ($id: ID!, $cursor: String) {
  collection(id: $id) {
    products(first: 250, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node { id } }
    }
  }
}
"""

CREATE_COLL_M = """
mutation ($input: CollectionInput!) {
  collectionCreate(input: $input) {
    collection { id handle }
    userErrors { field message }
  }
}
"""

UPDATE_COLL_M = """
mutation ($input: CollectionInput!) {
  collectionUpdate(input: $input) {
    collection { id sortOrder }
    userErrors { field message }
  }
}
"""

ADD_PRODUCTS_M = """
mutation ($id: ID!, $pids: [ID!]!) {
  collectionAddProducts(id: $id, productIds: $pids) {
    collection { id }
    userErrors { field message }
  }
}
"""

REMOVE_PRODUCTS_M = """
mutation ($id: ID!, $pids: [ID!]!) {
  collectionRemoveProducts(id: $id, productIds: $pids) {
    job { id done }
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

JOB_Q = """
query ($id: ID!) { job(id: $id) { id done } }
"""


def wait_job(client, job_id: str, timeout_s: int = 120) -> bool:
    import time
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        d = client.execute(JOB_Q, {"id": job_id})
        if d["job"]["done"]:
            return True
        time.sleep(2)
    return False


def fetch_collection_pids(client, coll_id: str) -> list[str]:
    out = []
    cursor = None
    while True:
        d = client.execute(LIST_PRODUCTS_Q, {"id": coll_id, "cursor": cursor})
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


def ensure_curated_collection(client) -> str:
    """Return the GID of the homepage-curated collection, creating it if missing."""
    d = client.execute(COLL_BY_HANDLE_Q, {"h": CURATED_HANDLE})
    if d["collectionByHandle"]:
        cid = d["collectionByHandle"]["id"]
        # Make sure sortOrder is MANUAL
        if d["collectionByHandle"]["sortOrder"] != "MANUAL":
            client.execute(UPDATE_COLL_M, {"input": {"id": cid, "sortOrder": "MANUAL"}})
        return cid
    print(f"creating collection {CURATED_HANDLE!r}...")
    inp = {
        "handle": CURATED_HANDLE,
        "title": CURATED_TITLE,
        "sortOrder": "MANUAL",
        "descriptionHtml": "Curated mix of top sellers across categories. Auto-updated daily.",
    }
    d = client.execute(CREATE_COLL_M, {"input": inp})
    errs = d["collectionCreate"]["userErrors"]
    if errs:
        raise RuntimeError(f"create failed: {errs}")
    return d["collectionCreate"]["collection"]["id"]


# ---------------------------------------------------------------------------
# Picking
# ---------------------------------------------------------------------------

def pick_top_in_stock(conn, client, cfg, today, coll_handle: str, n: int, exclude: set[str]) -> list[str]:
    """Return up to n top-scored, in-stock product IDs from the collection."""
    h = client.execute(COLL_BY_HANDLE_Q, {"h": coll_handle})["collectionByHandle"]
    if not h:
        print(f"  ! collection {coll_handle!r} not found"); return []
    pids = fetch_collection_pids(client, h["id"])
    if not pids:
        return []
    placeholders = ",".join("?" * len(pids))
    rows = conn.execute(
        f"SELECT * FROM products WHERE id IN ({placeholders})", pids
    ).fetchall()
    meta = {r["id"]: dict(r) for r in rows}
    eligible = [pid for pid in pids
                if pid in meta
                   and (meta[pid].get("status") or "").upper() == "ACTIVE"
                   and (meta[pid].get("total_inventory") or 0) > 0
                   and not meta[pid].get("external_only")   # never feature external-only goods
                   and pid not in exclude]
    if not eligible:
        return []
    scores = bs.compute_scores(conn, eligible, cfg, today)
    ranked = sorted(eligible, key=lambda p: (-scores.get(p, 0.0), meta[p].get("title") or ""))
    return ranked[:n]


def pick_wildcards(conn, exclude: set[str], n: int) -> list[str]:
    """Return n in-stock products: prefer Artmie + sale items, by score."""
    placeholders = ",".join("?" * len(exclude)) if exclude else None
    rows = conn.execute(
        f"""
        SELECT id, title, is_artmie, discount_pct
        FROM products
        WHERE status = 'ACTIVE'
          AND total_inventory > 0
          AND external_only = 0
          AND (is_artmie = 1 OR discount_pct >= 0.10)
          {f'AND id NOT IN ({placeholders})' if exclude else ''}
        """,
        list(exclude) if exclude else [],
    ).fetchall()
    if not rows:
        return []
    # Score using the same engine — pull just these IDs
    pids = [r["id"] for r in rows]
    scores = bs.compute_scores(conn, pids, cfg=_cached_cfg, today=_cached_today)
    # Prefer 1 Artmie + 1 sale if possible
    picks: list[str] = []
    artmie_ranked = sorted(
        (p for p in pids if dict(rows_by_id[p]).get("is_artmie")),
        key=lambda p: -scores.get(p, 0.0),
    )
    sale_ranked = sorted(
        (p for p in pids if (dict(rows_by_id[p]).get("discount_pct") or 0) >= 0.10
           and not dict(rows_by_id[p]).get("is_artmie")),
        key=lambda p: -scores.get(p, 0.0),
    )
    if artmie_ranked: picks.append(artmie_ranked[0])
    if len(picks) < n and sale_ranked:
        for p in sale_ranked:
            if p not in picks: picks.append(p); break
    # If still short, fill with top of either pool
    pool = sorted(pids, key=lambda p: -scores.get(p, 0.0))
    for p in pool:
        if len(picks) >= n: break
        if p not in picks: picks.append(p)
    return picks[:n]


# ugly cache so pick_wildcards can call compute_scores without re-passing cfg
_cached_cfg = None
_cached_today = None
rows_by_id = {}


# ---------------------------------------------------------------------------
# Apply: replace collection contents, then reorder
# ---------------------------------------------------------------------------

def replace_collection_contents(client, coll_id: str, new_pids: list[str], dry_run: bool):
    if dry_run:
        print("  [dry-run] would replace contents")
        return
    existing = fetch_collection_pids(client, coll_id)
    to_remove = [p for p in existing if p not in new_pids]
    to_add    = [p for p in new_pids if p not in existing]
    if to_remove:
        print(f"  removing {len(to_remove)} existing")
        d = client.execute(REMOVE_PRODUCTS_M, {"id": coll_id, "pids": to_remove})
        errs = d["collectionRemoveProducts"]["userErrors"]
        if errs: raise RuntimeError(f"remove errors: {errs}")
        job = d["collectionRemoveProducts"]["job"]
        if job and not wait_job(client, job["id"]):
            raise RuntimeError(f"remove job timeout")
    if to_add:
        print(f"  adding {len(to_add)} new")
        d = client.execute(ADD_PRODUCTS_M, {"id": coll_id, "pids": to_add})
        errs = d["collectionAddProducts"]["userErrors"]
        if errs: raise RuntimeError(f"add errors: {errs}")

    # Reorder to match new_pids order exactly
    moves = [{"id": pid, "newPosition": str(i)} for i, pid in enumerate(new_pids)]
    d = client.execute(REORDER_M, {"id": coll_id, "moves": moves})
    errs = d["collectionReorderProducts"]["userErrors"]
    if errs: raise RuntimeError(f"reorder errors: {errs}")
    job = d["collectionReorderProducts"]["job"]
    if job and not wait_job(client, job["id"]):
        raise RuntimeError(f"reorder job timeout")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=None, help="store code (default: sk / $ARTMIE_STORE)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    global _cached_cfg, _cached_today, rows_by_id
    cfg = cfg_mod.load(args.store)
    print(f"[{cfg.store}] shop: {cfg.shop.store_url}  mode: {cfg.mode}")
    if cfg.mode == "borrow":
        print(f"[{cfg.store}] mode=borrow — order-data homepage curation skipped "
              f"(use 06_multi_curate_homepage.py for non-order stores).")
        return
    _cached_cfg = cfg
    _cached_today = datetime.now(timezone.utc).date()
    client = ShopifyClient(cfg.shop)
    conn = db_mod.connect(cfg.db_path)
    db_mod.ensure_schema(conn)

    # Build recent-orders working set (needed by compute_scores)
    bs.ensure_recent_orders_table(conn, int(cfg.scoring["recent_orders_window"]))

    with db_mod.run(conn, "curate", notes="homepage 12-pick"):
        picks: list[str] = []
        per_category: list[tuple[str, list[str]]] = []

        # 1) Pick category-specific tops, deduping as we go
        for handle, n in CATEGORY_PICKS:
            cat_picks = pick_top_in_stock(conn, client, cfg, _cached_today, handle, n, set(picks))
            print(f"  {handle:35s} -> {len(cat_picks)} picked")
            per_category.append((handle, cat_picks))
            picks.extend(cat_picks)

        # 2) Wildcards (need rows_by_id for is_artmie + discount_pct lookups)
        all_active_rows = conn.execute(
            "SELECT id, is_artmie, discount_pct FROM products WHERE status='ACTIVE' AND total_inventory>0 AND external_only=0"
        ).fetchall()
        rows_by_id = {r["id"]: r for r in all_active_rows}
        wild = pick_wildcards(conn, set(picks), WILDCARD_COUNT)
        print(f"  wildcards (Artmie/sale)             -> {len(wild)} picked")
        per_category.append(("[wildcards]", wild))
        picks.extend(wild)

        if len(picks) < TOTAL_PICKS:
            print(f"WARNING: only {len(picks)} picks (expected {TOTAL_PICKS}). "
                  "Fewer in-stock candidates than slots.")

        # Show final pick list with titles
        print(f"\nFinal picks ({len(picks)}):")
        title_lookup = {r["id"]: r["title"] for r in conn.execute(
            f"SELECT id, title FROM products WHERE id IN ({','.join('?'*len(picks))})", picks
        )}
        for i, pid in enumerate(picks, 1):
            print(f"  {i:2d}. {title_lookup.get(pid, '?')[:75]}")

        # Apply to Shopify
        coll_id = ensure_curated_collection(client)
        print(f"\nupdating collection {CURATED_HANDLE} ({coll_id})...")
        replace_collection_contents(client, coll_id, picks, dry_run=args.dry_run)
        print(f"DONE — homepage-curated has {len(picks)} products in MANUAL order")


if __name__ == "__main__":
    main()
