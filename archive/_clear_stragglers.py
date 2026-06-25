"""Targeted cleanup for the 7 large-variant stragglers (>100 variants per product)
that the main cleanup pass missed because it only fetched the first 100 variants.

For each given product, fully paginate variants, find any with 0 < compareAtPrice <= price,
and null those compareAtPrice values.
"""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig
cfg = cfg_mod.load()

# (store, handle) pairs identified by _check_stragglers.py
STRAGGLERS = [
    ("BA", "slikarsko-platno-na-okviru-profi-artmie-razli-ite-dimenzije-ba-vxlpp"),
    ("BA", "akvarel-boje-schmincke-horadam-pola-posudice-ba-sch14044"),
    ("MK", "akvarelna-boja-schmincke-horadam-polovina-sad-mk-sch14044"),
]

PRODUCT_BY_HANDLE = "query ($h:String!){ productByHandle(handle:$h){ id handle title totalVariants } }"

ALL_VARIANTS_Q = """
query ($id: ID!, $cursor: String) {
  product(id: $id) {
    variants(first: 250, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node { id sku price compareAtPrice } }
    }
  }
}
"""

UPDATE_M = """
mutation ($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    userErrors { field message }
  }
}
"""

def fetch_all_variants(client, product_gid):
    out = []
    cursor = None
    while True:
        d = client.execute(ALL_VARIANTS_Q, {"id": product_gid, "cursor": cursor})
        for e in d["product"]["variants"]["edges"]:
            v = e["node"]
            try:
                p = float(v.get("price") or 0); ca = float(v.get("compareAtPrice") or 0)
            except: p, ca = 0, 0
            out.append((v["id"], v.get("sku") or "", p, ca))
        pi = d["product"]["variants"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]
    return out

# Resolve actual handle for the BA "slikarsko-platno..." entry by searching prefix
SEARCH_Q = "query ($q:String!){ products(first:1, query:$q){ edges{ node{ handle } } } }"

for code, handle_or_prefix in STRAGGLERS:
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    tok = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    if not url: print(f"[{code}] no env, skip"); continue
    shop = ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version)
    client = ShopifyClient(shop)

    # Resolve handle (some were truncated in display)
    d = client.execute(PRODUCT_BY_HANDLE, {"h": handle_or_prefix})
    p = d.get("productByHandle")
    if not p:
        # Try searching by handle prefix
        d2 = client.execute(SEARCH_Q, {"q": f"handle:{handle_or_prefix}*"})
        edges = d2["products"]["edges"]
        if not edges:
            print(f"[{code}] not found: {handle_or_prefix}"); continue
        actual = edges[0]["node"]["handle"]
        d = client.execute(PRODUCT_BY_HANDLE, {"h": actual})
        p = d["productByHandle"]
    print(f"\n[{code}] {p['handle']} (totalVariants={p['totalVariants']})")

    variants = fetch_all_variants(client, p["id"])
    fake_ids = [vid for (vid, sku, pr, ca) in variants if 0 < ca <= pr]
    real_count = sum(1 for (_v, _s, pr, ca) in variants if ca > pr)
    print(f"   fetched {len(variants)} variants  real_sale={real_count}  fake_to_clear={len(fake_ids)}")

    if real_count > 0:
        # Has at least one real sale variant — leave compareAt as-is (only clear if user wants)
        print(f"   SKIP: product has {real_count} real-sale variant(s); leaving fake variants alone")
        continue
    if not fake_ids:
        print(f"   SKIP: nothing to clear")
        continue

    # Chunk in 250 (mutation limit)
    for i in range(0, len(fake_ids), 250):
        chunk = fake_ids[i:i+250]
        payload = [{"id": vid, "compareAtPrice": None} for vid in chunk]
        d = client.execute(UPDATE_M, {"productId": p["id"], "variants": payload})
        errs = d["productVariantsBulkUpdate"]["userErrors"]
        if errs:
            print(f"   ! errors: {errs}")
        else:
            print(f"   cleared {len(chunk)} variants (chunk {i//250 + 1})")
