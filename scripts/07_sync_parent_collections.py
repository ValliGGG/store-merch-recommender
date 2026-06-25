"""Auto-sync parent collections to be the union of their descendants.

Per user 2026-04-26: parent menu categories should automatically include all
products from their child collections.  Shopify smart collections don't
support a "products in collection X" rule, so we maintain this via a script
that walks the navigation menu, finds every collection that has descendant
collections in the menu, and unions their products into the parent.

Default mode: ADDITIVE (safe) — products in any descendant are added to the
parent.  Existing products in the parent that aren't in any descendant are
LEFT ALONE.  Pass --replace to enforce strict union (extras get removed).

Deploy across stores by passing --store sk|pl|ba|mk (uses ARTMIE_<XX>_*
env vars from the shared .env).

Usage:
    python scripts/07_sync_parent_collections.py [--dry-run] [--replace] [--store sk]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig

# Menu handles to walk per store. The script walks the first menu that exists.
MENU_HANDLES = ["artmie-menu", "main-menu", "header-menu"]


# ---------------------------------------------------------------------------
# GraphQL
# ---------------------------------------------------------------------------

MENU_Q = """
{
  menus(first: 30) {
    edges { node { id handle title items { ...M items { ...M items { ...M items { ...M } } } } } }
  }
}
fragment M on MenuItem { id title type resourceId url }
"""

import re
HANDLE_RE = re.compile(r"/collections/([a-z0-9_-]+)/?", re.IGNORECASE)

COLL_PIDS_Q = """
query ($id: ID!, $cursor: String) {
  collection(id: $id) {
    handle title sortOrder ruleSet { rules { column relation condition } }
    products(first: 250, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node { id } }
    }
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

JOB_Q = "query ($id: ID!) { job(id: $id) { id done } }"

PUBLISH_M = """
mutation ($id: ID!, $inputs: [PublicationInput!]!) {
  publishablePublish(id: $id, input: $inputs) {
    publishable { availablePublicationsCount { count } }
    userErrors { field message }
  }
}
"""

PUBS_Q = """
{ publications(first: 20) { edges { node { id name } } } }
"""

# Channel name patterns we always publish parent collections to.  Anything
# matching gets published — covers Online Store + Headless storefronts on SK.
PUBLISH_PATTERNS = ["online store", "headless", "storefront"]


def get_channels_to_publish(client) -> list[str]:
    d = client.execute(PUBS_Q)
    out = []
    for e in d["publications"]["edges"]:
        name = e["node"]["name"].lower()
        if any(p in name for p in PUBLISH_PATTERNS):
            out.append(e["node"]["id"])
    return out


def wait_job(client, job_id: str, timeout_s: int = 180) -> bool:
    import time
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if client.execute(JOB_Q, {"id": job_id})["job"]["done"]:
            return True
        time.sleep(2)
    return False


# ---------------------------------------------------------------------------
# Menu walking
# ---------------------------------------------------------------------------

def walk_items(items: list[dict]) -> list[dict]:
    out = []
    for item in items or []:
        out.append(item)
        out.extend(walk_items(item.get("items") or []))
    return out


def item_collection_handle(item: dict) -> str | None:
    """Extract the collection handle from a menu item, regardless of whether
    it's typed COLLECTION (uses resourceId) or HTTP (uses url=/collections/X)."""
    if item.get("type") == "COLLECTION" and item.get("resourceId"):
        return None   # caller will use resourceId directly
    url = item.get("url")
    if not url:
        return None
    m = HANDLE_RE.search(url)
    return m.group(1).lower() if m else None


def resolve_handle(client, cache: dict, handle: str) -> str | None:
    """Look up a collection handle to a GID, with caching."""
    if handle in cache:
        return cache[handle]
    d = client.execute("query ($h:String!){ collectionByHandle(handle:$h){ id } }", {"h": handle})
    gid = (d.get("collectionByHandle") or {}).get("id")
    cache[handle] = gid
    return gid


def get_parent_collections(menu: dict, client) -> list[tuple[dict, list[str]]]:
    """For each unique parent collection in the menu (regardless of type
    COLLECTION vs HTTP), return (representative_item, deduped_descendant_gids)."""
    handle_cache: dict[str, str | None] = {}

    def to_gid(item):
        if item.get("type") == "COLLECTION" and item.get("resourceId"):
            return item["resourceId"]
        h = item_collection_handle(item)
        return resolve_handle(client, handle_cache, h) if h else None

    def collection_descendants(item: dict) -> list[str]:
        gids = []
        def _walk(node):
            for child in node.get("items") or []:
                gid = to_gid(child)
                if gid:
                    gids.append(gid)
                _walk(child)
        _walk(item)
        return list(dict.fromkeys(gids))

    by_parent: dict[str, dict] = {}

    def _walk(items):
        for item in items or []:
            pgid = to_gid(item)
            if pgid:
                desc = collection_descendants(item)
                if desc:
                    bucket = by_parent.setdefault(pgid, {"item": item, "descendants": set()})
                    bucket["descendants"].update(desc)
            _walk(item.get("items"))
    _walk(menu.get("items"))

    out = []
    for pgid, bucket in by_parent.items():
        descendants = [d for d in bucket["descendants"] if d != pgid]
        if descendants:
            # Attach the resolved GID to the item so the main loop doesn't need
            # to re-resolve from a possibly-missing resourceId
            item = dict(bucket["item"])
            item["_resolved_gid"] = pgid
            out.append((item, descendants))
    return out


# ---------------------------------------------------------------------------
# Collection ops
# ---------------------------------------------------------------------------

def fetch_pids(client, coll_gid: str) -> tuple[list[str], dict]:
    """Return (product_gids, collection_metadata).  metadata has handle, title, ruleSet."""
    pids = []
    meta = {}
    cursor = None
    while True:
        d = client.execute(COLL_PIDS_Q, {"id": coll_gid, "cursor": cursor})
        coll = d["collection"]
        if not coll:
            return [], {}
        if not meta:
            meta = {"handle": coll["handle"], "title": coll["title"],
                    "sortOrder": coll["sortOrder"], "ruleSet": coll.get("ruleSet")}
        for e in coll["products"]["edges"]:
            pids.append(e["node"]["id"])
        pi = coll["products"]["pageInfo"]
        if not pi["hasNextPage"]:
            break
        cursor = pi["endCursor"]
    return pids, meta


def add_products_batched(client, coll_gid: str, pids: list[str], batch: int = 250):
    for i in range(0, len(pids), batch):
        chunk = pids[i:i + batch]
        d = client.execute(ADD_PRODUCTS_M, {"id": coll_gid, "pids": chunk})
        errs = d["collectionAddProducts"]["userErrors"]
        if errs:
            print(f"    add errors (chunk {i}): {errs[:2]}", file=sys.stderr)


def remove_products_batched(client, coll_gid: str, pids: list[str], batch: int = 100):
    for i in range(0, len(pids), batch):
        chunk = pids[i:i + batch]
        d = client.execute(REMOVE_PRODUCTS_M, {"id": coll_gid, "pids": chunk})
        errs = d["collectionRemoveProducts"]["userErrors"]
        if errs:
            print(f"    remove errors (chunk {i}): {errs[:2]}", file=sys.stderr)
        job = d["collectionRemoveProducts"]["job"]
        if job and not wait_job(client, job["id"]):
            print(f"    remove job timeout", file=sys.stderr)


# ---------------------------------------------------------------------------
# Per-store driver
# ---------------------------------------------------------------------------

def make_shop_config(store_code: str, base_cfg) -> ShopConfig:
    code = store_code.upper()
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    token = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    if not url or not token:
        print(f"ERROR: missing ARTMIE_{code}_STORE_URL or ARTMIE_{code}_API_TOKEN", file=sys.stderr)
        sys.exit(2)
    return ShopConfig(store_url=url, api_token=token, api_version=base_cfg.shop.api_version)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="sk",
                    choices=["sk", "cz", "pl", "hu", "ro", "mk", "rs", "ba"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replace", action="store_true",
                    help="Strict union: remove products from parent that aren't in any descendant")
    args = ap.parse_args()

    base_cfg = cfg_mod.load(args.store)
    shop = make_shop_config(args.store, base_cfg)
    client = ShopifyClient(shop)
    print(f"store: {shop.store_url}  mode: {'REPLACE' if args.replace else 'ADDITIVE'}"
          + ("  [dry-run]" if args.dry_run else ""))

    # 1. Find the artmie menu (or fallback)
    d = client.execute(MENU_Q)
    menus = {e["node"]["handle"]: e["node"] for e in d["menus"]["edges"]}
    menu = next((menus[h] for h in MENU_HANDLES if h in menus), None)
    if not menu:
        # Heuristic: pick the menu with the most COLLECTION items
        candidates = []
        for m in menus.values():
            cnt = sum(1 for it in walk_items(m.get("items") or []) if it.get("type") == "COLLECTION")
            candidates.append((cnt, m))
        candidates.sort(reverse=True, key=lambda x: x[0])
        menu = candidates[0][1] if candidates else None
        print(f"  using menu: {menu['handle']!r} (auto-picked, {candidates[0][0]} collection items)")
    else:
        print(f"  using menu: {menu['handle']!r}")

    parents = get_parent_collections(menu, client)
    print(f"  parent collections to sync: {len(parents)}")
    if not parents:
        print("nothing to do."); return

    # Channels that every parent must be published to (so storefront can see them)
    publish_channels = get_channels_to_publish(client)
    print(f"  publish channels: {len(publish_channels)} ({', '.join(c.split('/')[-1] for c in publish_channels)})")

    # 2. For each parent, gather descendants → union products → sync into parent
    total_added = 0
    total_removed = 0
    total_published = 0
    for parent_item, descendant_gids in parents:
        parent_gid = parent_item.get("_resolved_gid") or parent_item.get("resourceId")
        if not parent_gid:
            print(f"  ! {parent_item.get('title','?')!r} -> no GID, skip")
            continue
        parent_pids, parent_meta = fetch_pids(client, parent_gid)
        if not parent_meta:
            print(f"  ! {parent_item['title']!r} -> parent collection not found, skip"); continue

        # Skip smart collections (can't add products to rule-based collections)
        if parent_meta.get("ruleSet"):
            print(f"  - {parent_meta['handle']:35s} smart collection (rule-based), skip")
            continue

        # Union descendant products
        descendant_pid_set = set()
        for desc_gid in descendant_gids:
            d_pids, _ = fetch_pids(client, desc_gid)
            descendant_pid_set.update(d_pids)

        parent_pid_set = set(parent_pids)
        to_add = list(descendant_pid_set - parent_pid_set)
        to_remove = list(parent_pid_set - descendant_pid_set) if args.replace else []

        action = []
        if to_add:    action.append(f"+{len(to_add)}")
        if to_remove: action.append(f"-{len(to_remove)}")
        action_str = " ".join(action) or "(no changes)"

        print(f"  - {parent_meta['handle']:35s} parent={len(parent_pids)} desc_union={len(descendant_pid_set)} {action_str}")

        if args.dry_run:
            continue
        if to_add:
            add_products_batched(client, parent_gid, to_add)
            total_added += len(to_add)
        if to_remove:
            remove_products_batched(client, parent_gid, to_remove)
            total_removed += len(to_remove)

        # Always (re-)publish to ensure customer visibility (idempotent — Shopify ignores duplicate publishes)
        if publish_channels:
            try:
                inputs = [{"publicationId": p} for p in publish_channels]
                d = client.execute(PUBLISH_M, {"id": parent_gid, "inputs": inputs})
                errs = d["publishablePublish"]["userErrors"]
                if errs:
                    print(f"    publish warn: {errs[:2]}", file=sys.stderr)
                else:
                    total_published += 1
            except Exception as e:
                print(f"    publish failed: {e}", file=sys.stderr)

    print(f"\nDONE — {total_added} products added, {total_removed} removed, "
          f"{total_published} parents (re-)published across {len(parents)} parent collections"
          + (" [dry-run]" if args.dry_run else ""))


if __name__ == "__main__":
    main()
