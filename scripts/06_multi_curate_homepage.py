"""Multi-store homepage curator for PL/BA/MK (and SK fallback).

For SK, prefer scripts/06_curate_homepage.py (uses real order data + scoring).
For PL/BA/MK, we don't have order data, so we pick the top N IN-STOCK
products from each category collection in their current order.  After
scripts/08_in_stock_first_reorder.py runs, that "current order" already
has in-stock products at the top, so this script naturally picks fresh,
in-stock items.

Per-store collection mapping (mirrors the user's slot specification):
  Slots 1-2: bestsellers
  Slots 3-4: paints
  Slots 5-6: brushes
  Slot 7:    canvas
  Slots 8-9: kids
  Slot 10:   paper
  Slots 11-12: in-stock Artmie / sale / extra category wildcards

Idempotent.  Creates the homepage-curated collection if missing, populates
with 12 in-stock products in fixed order, publishes to Online Store, and
points the homepage `product_list_fa6P9H` (or `plist_bestsellers`) section at it.
"""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig


CURATED_HANDLE = "homepage-curated"

# Per-store collection handle mapping for slot composition.
# (collection_handle, count, label_for_logging)
STORE_PICKS = {
    "PL": [
        ("bestsellery",                      2, "bestsellers"),
        ("farby-artystyczne",                2, "paints"),
        ("pedzle-artystyczne-i-akcesoria",   2, "brushes"),
        ("podobrazia-malarskie",             1, "canvas"),
        ("artykuy-kreatywne-dla-dzieci",     2, "kids"),
        ("papier-i-arkusze-rysunkowe",       1, "paper"),
        # Wildcards: pull from PROMOCJE (sale) collection for high-discount items
        ("promocje",                         2, "sale-wildcards"),
    ],
    "BA": [
        ("noviteti",                         2, "bestsellers"),
        ("umjetnicke-boje",                  2, "paints"),
        ("umjetnicki-kistovi-i-pribor",      2, "brushes"),
        ("slikarska-platna",                 1, "canvas"),
        ("kreativno-za-djecu-grupa",         2, "kids"),
        ("papir-scrapbook-dekupaz",          1, "paper"),
        ("akcije",                           2, "sale-wildcards"),
    ],
    "MK": [
        ("noviteti",                         2, "bestsellers"),
        ("umetnichki-boi",                   2, "paints"),
        ("umetnicki-cetki-i-pomagala",       2, "brushes"),
        ("slikarski-platna",                 1, "canvas"),
        ("kreativni-za-deca-grupa",          2, "kids"),
        ("hartija-scrapbook-dekupazh",       1, "paper"),
        ("artmie",                           2, "artmie-wildcards"),
    ],
}


# ---------------------------------------------------------------------------
# GraphQL
# ---------------------------------------------------------------------------

COLL_BY_HANDLE_Q = """
query ($h: String!) { collectionByHandle(handle: $h) { id title sortOrder } }
"""

LIST_PRODUCTS_Q = """
query ($id: ID!, $cursor: String) {
  collection(id: $id) {
    products(first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node { id title totalInventory } }
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
    collection { id }
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

PUBLISH_M = """
mutation ($id: ID!, $inputs: [PublicationInput!]!) {
  publishablePublish(id: $id, input: $inputs) {
    userErrors { field message }
  }
}
"""

PUBS_Q = "{ publications(first: 20) { edges { node { id name } } } }"
JOB_Q = "query ($id:ID!){ job(id:$id) { id done } }"


def wait_job(client, job_id: str, timeout_s: int = 120) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if client.execute(JOB_Q, {"id": job_id})["job"]["done"]:
            return True
        time.sleep(2)
    return False


def get_online_store_pub(client) -> str | None:
    d = client.execute(PUBS_Q)
    for e in d["publications"]["edges"]:
        if e["node"]["name"].lower() == "online store":
            return e["node"]["id"]
    return None


def fetch_top_in_stock(client, handle: str, n: int, exclude: set[str]) -> list[str]:
    """Walk the collection in current sort order (which after script 08 has
    in-stock products at top), return the first n in-stock product IDs that
    aren't already in exclude."""
    h = client.execute(COLL_BY_HANDLE_Q, {"h": handle}).get("collectionByHandle")
    if not h:
        return []
    out = []
    cursor = None
    while True:
        d = client.execute(LIST_PRODUCTS_Q, {"id": h["id"], "cursor": cursor})
        coll = d["collection"]
        for e in coll["products"]["edges"]:
            pid = e["node"]["id"]
            inv = int(e["node"].get("totalInventory") or 0)
            if pid in exclude or inv <= 0:
                continue
            out.append(pid)
            if len(out) >= n:
                return out
        pi = coll["products"]["pageInfo"]
        if not pi["hasNextPage"]:
            break
        cursor = pi["endCursor"]
    return out


def ensure_curated_collection(client) -> str:
    d = client.execute(COLL_BY_HANDLE_Q, {"h": CURATED_HANDLE})
    if d["collectionByHandle"]:
        cid = d["collectionByHandle"]["id"]
        if d["collectionByHandle"]["sortOrder"] != "MANUAL":
            client.execute(UPDATE_COLL_M, {"input": {"id": cid, "sortOrder": "MANUAL"}})
        return cid
    inp = {
        "handle": CURATED_HANDLE,
        "title":  "Odporúčame TOP PICKS",
        "sortOrder": "MANUAL",
        "descriptionHtml": "Curated mix of in-stock products across categories. Auto-updated daily.",
    }
    d = client.execute(CREATE_COLL_M, {"input": inp})
    errs = d["collectionCreate"]["userErrors"]
    if errs: raise RuntimeError(f"create failed: {errs}")
    return d["collectionCreate"]["collection"]["id"]


def fetch_collection_pids(client, cid: str) -> list[str]:
    out = []
    cursor = None
    while True:
        d = client.execute(LIST_PRODUCTS_Q, {"id": cid, "cursor": cursor})
        coll = d["collection"]
        if not coll: return out
        for e in coll["products"]["edges"]:
            out.append(e["node"]["id"])
        pi = coll["products"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]
    return out


def replace_contents(client, coll_id: str, new_pids: list[str], dry_run: bool):
    existing = fetch_collection_pids(client, coll_id)
    to_remove = [p for p in existing if p not in new_pids]
    to_add    = [p for p in new_pids if p not in existing]
    if dry_run:
        print(f"  [dry-run] would add={len(to_add)} remove={len(to_remove)}")
        return
    if to_remove:
        d = client.execute(REMOVE_PRODUCTS_M, {"id": coll_id, "pids": to_remove})
        errs = d["collectionRemoveProducts"]["userErrors"]
        if errs: raise RuntimeError(f"remove errors: {errs}")
        job = d["collectionRemoveProducts"]["job"]
        if job and not wait_job(client, job["id"]):
            raise RuntimeError("remove timeout")
    if to_add:
        d = client.execute(ADD_PRODUCTS_M, {"id": coll_id, "pids": to_add})
        errs = d["collectionAddProducts"]["userErrors"]
        if errs: raise RuntimeError(f"add errors: {errs}")
    moves = [{"id": pid, "newPosition": str(i)} for i, pid in enumerate(new_pids)]
    d = client.execute(REORDER_M, {"id": coll_id, "moves": moves})
    errs = d["collectionReorderProducts"]["userErrors"]
    if errs: raise RuntimeError(f"reorder errors: {errs}")
    job = d["collectionReorderProducts"]["job"]
    if job and not wait_job(client, job["id"]):
        raise RuntimeError("reorder timeout")


# ---------------------------------------------------------------------------
# Theme update — point homepage product_list section to homepage-curated
# ---------------------------------------------------------------------------

THEMES_Q = "{ themes(first: 20) { edges { node { id name role } } } }"
TEMPLATE_FETCH_Q = """
query ($id:ID!) {
  theme(id:$id) { files(first:1, filenames:["templates/index.json"]) {
    nodes { body { ... on OnlineStoreThemeFileBodyText { content } } }
  } }
}
"""
TEMPLATE_UPSERT_M = """
mutation ($themeId:ID!, $files:[OnlineStoreThemeFilesUpsertFileInput!]!) {
  themeFilesUpsert(themeId:$themeId, files:$files) {
    upsertedThemeFiles { filename }
    userErrors { filename code message }
  }
}
"""


def repoint_homepage_tile(client) -> str:
    """Update templates/index.json so the product-list section points at homepage-curated.
    Handles both `product_list_fa6P9H` (PL/BA/MK Horizon default) and
    `plist_bestsellers` (SK custom).  Returns short status message."""
    d = client.execute(THEMES_Q)
    main = next((e["node"] for e in d["themes"]["edges"] if e["node"]["role"] == "MAIN"), None)
    if not main:
        return "no MAIN theme"
    d = client.execute(TEMPLATE_FETCH_Q, {"id": main["id"]})
    nodes = d["theme"]["files"]["nodes"]
    if not nodes:
        return "no templates/index.json"
    content = nodes[0]["body"]["content"]
    header_end = content.find("*/") + 2 if content.lstrip().startswith("/*") else 0
    header = content[:header_end]
    data = json.loads(content[header_end:])

    candidate_keys = ["plist_bestsellers", "product_list_fa6P9H"]
    target_key = next((k for k in candidate_keys if k in data.get("sections", {})), None)
    if not target_key:
        # Find any product-list section
        for k, v in data.get("sections", {}).items():
            if v.get("type") == "product-list":
                target_key = k; break
    if not target_key:
        return "no product-list section in template"

    sec = data["sections"][target_key]
    sec.setdefault("settings", {})
    sec["settings"]["collection"] = CURATED_HANDLE
    sec["settings"]["max_products"] = 12

    new_content = header + "\n" + json.dumps(data, indent=2, ensure_ascii=False)
    r = client.execute(TEMPLATE_UPSERT_M, {
        "themeId": main["id"],
        "files": [{"filename": "templates/index.json",
                   "body": {"type": "TEXT", "value": new_content}}],
    })
    errs = r["themeFilesUpsert"]["userErrors"]
    if errs:
        return f"theme update errors: {errs}"
    return f"updated section {target_key} -> {CURATED_HANDLE} (max=12)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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
    print(f"store: {url}")

    if code not in STORE_PICKS:
        print(f"  no STORE_PICKS for {code}"); return
    picks_spec = STORE_PICKS[code]

    selected: list[str] = []
    for handle, n, label in picks_spec:
        cat_picks = fetch_top_in_stock(client, handle, n, set(selected))
        if len(cat_picks) < n:
            print(f"  ! {handle:35s} ({label}) only got {len(cat_picks)}/{n} in-stock picks")
        else:
            print(f"  - {handle:35s} ({label}) +{len(cat_picks)}")
        selected.extend(cat_picks)

    print(f"\ntotal picks: {len(selected)}")
    if not selected:
        print("nothing to do"); return

    # Show titles for verification
    if selected:
        Q = """query ($ids:[ID!]!){ nodes(ids:$ids){ ... on Product { id title totalInventory } } }"""
        d = client.execute(Q, {"ids": selected})
        title_lookup = {n["id"]: n.get("title","?") for n in d["nodes"] if n}
        print("\nFinal picks:")
        for i, pid in enumerate(selected, 1):
            print(f"  {i:2d}. {title_lookup.get(pid,'?')[:75]}")

    # Apply
    coll_id = ensure_curated_collection(client)
    print(f"\nupdating collection {CURATED_HANDLE} ({coll_id})...")
    replace_contents(client, coll_id, selected, dry_run=args.dry_run)
    if not args.dry_run:
        # Publish to Online Store
        pub = get_online_store_pub(client)
        if pub:
            client.execute(PUBLISH_M, {"id": coll_id, "inputs": [{"publicationId": pub}]})
            print(f"  published to Online Store")
        # Point homepage tile
        msg = repoint_homepage_tile(client)
        print(f"  theme: {msg}")
    print(f"DONE — {len(selected)} products in homepage-curated{' [dry-run]' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
