"""Audit each store's promotion collection: find products inside that aren't actually on sale.

A product is considered ON SALE when at least one variant has compareAtPrice > price.
Anything else in the promo collection is a stale/incorrect inclusion.
"""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig

cfg = cfg_mod.load()

# Best-guess promo handles per store; we'll also auto-detect via menu / collection search
PROMO_HANDLES = {
    "SK": ["vypredaj", "zlavy", "akcie", "vypredaj-2", "akcia"],
    "PL": ["promocje", "wyprzedaz", "wyprzedaze"],
    "BA": ["rasprodaja", "popusti", "akcija"],
    "MK": ["rasprodazba", "popust", "namalenija", "akcija"],
}

FIND_COLL_Q = """
query ($handle: String!) {
  collectionByHandle(handle: $handle) {
    id title handle productsCount { count }
    ruleSet { appliedDisjunctively rules { column relation condition } }
  }
}
"""

LIST_COLL_Q = """
query ($cursor: String) {
  collections(first: 50, after: $cursor, query: "title:*sale* OR title:*promo* OR title:*akci* OR title:*zlav* OR title:*wyprz* OR title:*rasprod* OR title:*popust* OR title:*namalen*") {
    pageInfo { hasNextPage endCursor }
    edges { node { id title handle productsCount { count } } }
  }
}
"""

PROMO_PRODUCTS_Q = """
query ($id: ID!, $cursor: String) {
  collection(id: $id) {
    products(first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node {
        id handle title totalInventory
        priceRangeV2 { minVariantPrice { amount } maxVariantPrice { amount } }
        compareAtPriceRange { minVariantCompareAtPrice { amount } maxVariantCompareAtPrice { amount } }
      } }
    }
  }
}
"""

def is_on_sale(node):
    """A product is on sale if max compareAt > min price (any variant has a strikethrough)."""
    car = node.get("compareAtPriceRange") or {}
    pr  = node.get("priceRangeV2") or {}
    try:
        ca_max = float((car.get("maxVariantCompareAtPrice") or {}).get("amount") or 0)
        p_min  = float((pr.get("minVariantPrice") or {}).get("amount") or 0)
    except (TypeError, ValueError):
        return False
    return ca_max > 0 and ca_max > p_min

for code in ["SK", "PL", "BA", "MK"]:
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    tok = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    if not url:
        print(f"[{code}] no env, skip"); continue
    shop = ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version)
    client = ShopifyClient(shop)

    # Resolve promo collection
    promo = None
    for h in PROMO_HANDLES[code]:
        d = client.execute(FIND_COLL_Q, {"handle": h})
        if d.get("collectionByHandle"):
            promo = d["collectionByHandle"]; break
    if not promo:
        # Search by title
        d = client.execute(LIST_COLL_Q, {"cursor": None})
        cands = [e["node"] for e in d["collections"]["edges"]]
        if cands:
            print(f"[{code}] no exact handle match. Candidates by title:")
            for c in cands[:10]:
                print(f"   - {c['handle']:35s} {c['title']}  ({c['productsCount']['count']} products)")
            continue
        print(f"[{code}] no promo collection found"); continue

    print(f"\n[{code}] promo: {promo['handle']}  title='{promo['title']}'  total={promo['productsCount']['count']}")
    smart = bool(promo.get("ruleSet"))
    if smart:
        print(f"   SMART collection. Rules: {promo['ruleSet']['rules']}")
    else:
        print(f"   MANUAL collection (no auto-rules)")

    # Walk products, classify
    not_on_sale = []
    on_sale = 0
    cursor = None
    while True:
        d = client.execute(PROMO_PRODUCTS_Q, {"id": promo["id"], "cursor": cursor})
        coll = d["collection"]
        for e in coll["products"]["edges"]:
            n = e["node"]
            if is_on_sale(n):
                on_sale += 1
            else:
                not_on_sale.append((n["handle"], n["title"], n["totalInventory"]))
        pi = coll["products"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]

    print(f"   on-sale: {on_sale}   NOT on sale: {len(not_on_sale)}")
    for h, t, inv in not_on_sale[:8]:
        print(f"     - {h[:45]:45s} inv={inv}  {t[:40]}")
    if len(not_on_sale) > 8:
        print(f"     ... and {len(not_on_sale)-8} more")
