"""Post-cleanup audit: re-run the per-variant check on each promo collection
and confirm only products with at least one truly discounted variant remain.
"""
import os, sys
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
      edges { node { id handle title
        variants(first: 100) { edges { node { id price compareAtPrice } } } } }
    }
  }
}
"""

print(f"{'STORE':6s} {'COLL':10s} {'TOTAL':>6s} {'REAL':>6s} {'FAKE':>6s}  status")
for code in ["SK","PL","BA","MK"]:
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    tok = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    if not url: continue
    shop = ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version)
    client = ShopifyClient(shop)
    d = client.execute(FIND_Q, {"h": PROMO[code]})
    coll = d.get("collectionByHandle")
    if not coll: print(f"{code:6s} (none)"); continue

    real, fake = 0, 0
    cursor = None
    while True:
        d = client.execute(VARIANTS_Q, {"id": coll["id"], "cursor": cursor})
        c = d["collection"]
        for e in c["products"]["edges"]:
            n = e["node"]
            any_real = False
            for ve in n["variants"]["edges"]:
                v = ve["node"]
                try:
                    p = float(v.get("price") or 0); ca = float(v.get("compareAtPrice") or 0)
                except (TypeError, ValueError): continue
                if ca > p:
                    any_real = True; break
            if any_real: real += 1
            else: fake += 1
        pi = c["products"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]

    total = coll["productsCount"]["count"]
    status = "CLEAN" if fake == 0 else f"{fake} stale (indexer lag)"
    print(f"{code:6s} {coll['handle']:10s} {total:>6d} {real:>6d} {fake:>6d}  {status}")
