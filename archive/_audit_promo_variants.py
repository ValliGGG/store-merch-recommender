"""Per-variant audit: for each promo-collection product, check if ANY variant truly has
compareAtPrice > price (= real sale). If none, the product is wrongly in the promo collection
because its compareAt is set but <= price (data error, no real discount).
"""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig

cfg = cfg_mod.load()

PROMO = {"SK":"zlava", "PL":"promocje", "BA":"akcije", "MK":"popusti"}

FIND_Q = "query ($h:String!){ collectionByHandle(handle:$h){ id handle productsCount{count} } }"

# Fetch all variants per product, check compareAt > price
VARIANTS_Q = """
query ($id: ID!, $cursor: String) {
  collection(id: $id) {
    products(first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node {
        id handle title totalInventory
        variants(first: 100) { edges { node { id sku price compareAtPrice inventoryQuantity } } }
      } }
    }
  }
}
"""

for code in ["SK", "PL", "BA", "MK"]:
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    tok = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    if not url: continue
    shop = ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version)
    client = ShopifyClient(shop)

    d = client.execute(FIND_Q, {"h": PROMO[code]})
    coll = d.get("collectionByHandle")
    if not coll:
        print(f"[{code}] no promo {PROMO[code]}"); continue

    print(f"\n[{code}] {coll['handle']} total={coll['productsCount']['count']}")
    real_sale = 0
    fake_sale = []           # product has compareAt set on some variant but no variant has compareAt > price
    fake_var_count = 0       # number of "fake compareAt" variants needing nulled
    cursor = None
    while True:
        d = client.execute(VARIANTS_Q, {"id": coll["id"], "cursor": cursor})
        c = d["collection"]
        for e in c["products"]["edges"]:
            n = e["node"]
            any_real_sale = False
            fake_var_ids = []
            for ve in n["variants"]["edges"]:
                v = ve["node"]
                try:
                    p  = float(v.get("price") or 0)
                    ca = float(v.get("compareAtPrice") or 0)
                except (TypeError, ValueError):
                    continue
                if ca > p:
                    any_real_sale = True
                elif ca > 0 and ca <= p:
                    fake_var_ids.append(v["id"])
            if any_real_sale:
                real_sale += 1
            else:
                fake_sale.append((n["handle"], n["title"], n["totalInventory"], fake_var_ids))
                fake_var_count += len(fake_var_ids)
        pi = c["products"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]

    print(f"   real sale: {real_sale}   FAKE (no variant compareAt>price): {len(fake_sale)}   "
          f"variants to clear: {fake_var_count}")
    for h, t, inv, vids in fake_sale[:5]:
        print(f"     - {h[:42]:42s} inv={inv}  variants_to_clear={len(vids)}  {t[:35]}")
