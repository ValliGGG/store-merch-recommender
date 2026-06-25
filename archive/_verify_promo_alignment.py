"""Final verification: are PL/BA/MK on-sale SKU sets now aligned with SK?

Counts to expect after both mirror + unmirror:
  - aligned         = SKUs on sale in T that match an on-sale SKU in SK  (should be: SK_set & T_set)
  - extras_in_T     = T-only on-sale SKUs (should be 0 after un-mirror)
  - missing_in_T    = SK-only on-sale SKUs (= SK SKUs that don't exist in T catalog at all)
"""
import os, sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig
cfg = cfg_mod.load()

PROMO = {"SK":"zlava", "PL":"promocje", "BA":"akcije", "MK":"popusti"}

FIND_Q = "query ($h:String!){ collectionByHandle(handle:$h){ id handle productsCount{count} } }"
VARIANTS_Q = """
query ($id: ID!, $cursor: String) {
  collection(id: $id) {
    products(first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node { id handle
        variants(first: 250) { pageInfo{hasNextPage endCursor}
          edges { node { sku price compareAtPrice } } } } }
    }
  }
}
"""
PV_Q = """
query ($id: ID!, $cursor: String) {
  product(id: $id) { variants(first: 250, after: $cursor) {
    pageInfo{hasNextPage endCursor} edges { node { sku price compareAtPrice } } } }
}
"""

def get_client(code):
    url = os.environ[f"ARTMIE_{code}_STORE_URL"]
    tok = os.environ[f"ARTMIE_{code}_API_TOKEN"]
    return ShopifyClient(ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version))

def fetch_on_sale_skus(code):
    client = get_client(code)
    coll = client.execute(FIND_Q, {"h": PROMO[code]})["collectionByHandle"]
    skus = set()
    cursor = None
    while True:
        d = client.execute(VARIANTS_Q, {"id": coll["id"], "cursor": cursor})
        c = d["collection"]
        for e in c["products"]["edges"]:
            n = e["node"]
            vs = list(n["variants"]["edges"])
            v_pi = n["variants"]["pageInfo"]
            cur = v_pi["endCursor"] if v_pi["hasNextPage"] else None
            while cur:
                d2 = client.execute(PV_Q, {"id": n["id"], "cursor": cur})
                vs.extend(d2["product"]["variants"]["edges"])
                pi2 = d2["product"]["variants"]["pageInfo"]
                cur = pi2["endCursor"] if pi2["hasNextPage"] else None
            for ve in vs:
                v = ve["node"]
                sku = (v.get("sku") or "").strip()
                if not sku: continue
                try:
                    p = float(v.get("price") or 0); ca = float(v.get("compareAtPrice") or 0)
                except: continue
                if ca > p:
                    skus.add(sku)
        pi = c["products"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]
    return skus, coll["productsCount"]["count"]

print("Fetching on-sale SKU sets (truth from per-variant scan, not cached count)...")
results = {}
for code in ["SK","PL","BA","MK"]:
    skus, cached = fetch_on_sale_skus(code)
    results[code] = skus
    print(f"  {code}: {len(skus):4d} on-sale SKUs   (cached productsCount={cached})")

sk = results["SK"]
print(f"\nAlignment vs SK ({len(sk)} on-sale SKUs as source of truth):")
print(f"  {'STORE':6s} {'on-sale':>7s} {'aligned':>8s} {'extras':>6s} {'sk-only':>8s}")
for code in ["PL","BA","MK"]:
    t = results[code]
    aligned = sk & t
    extras = t - sk
    sk_only = sk - t
    print(f"  {code:6s} {len(t):>7d} {len(aligned):>8d} {len(extras):>6d} {len(sk_only):>8d}")
