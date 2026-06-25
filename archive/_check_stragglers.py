"""Investigate the few products still classified as 'fake' post-cleanup."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig
cfg = cfg_mod.load()

PROMO = {"BA":"akcije", "MK":"popusti"}
FIND_Q = "query ($h:String!){ collectionByHandle(handle:$h){ id handle } }"
LIST_Q = """
query ($id: ID!, $cursor: String) {
  collection(id: $id) {
    products(first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node {
        id handle title totalVariants
        variants(first: 250) { edges { node { sku price compareAtPrice } } }
      } }
    }
  }
}
"""

for code in ["BA","MK"]:
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    tok = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    if not url: continue
    shop = ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version)
    client = ShopifyClient(shop)
    d = client.execute(FIND_Q, {"h": PROMO[code]}); coll_id = d["collectionByHandle"]["id"]
    print(f"\n[{code}] {PROMO[code]} stragglers:")
    cursor = None
    while True:
        d = client.execute(LIST_Q, {"id": coll_id, "cursor": cursor})
        c = d["collection"]
        for e in c["products"]["edges"]:
            n = e["node"]
            any_real = False; max_ca = 0; min_p = float("inf"); n_vars = 0
            for ve in n["variants"]["edges"]:
                v = ve["node"]
                try:
                    p = float(v.get("price") or 0); ca = float(v.get("compareAtPrice") or 0)
                except: continue
                n_vars += 1
                max_ca = max(max_ca, ca); min_p = min(min_p, p)
                if ca > p: any_real = True
            if not any_real:
                tv = n.get("totalVariants") or 0
                print(f"   {n['handle'][:55]:55s} totalVariants={tv} sampled={n_vars}  "
                      f"max_ca={max_ca}  min_p={min_p}  '{n['title'][:35]}'")
        pi = c["products"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]
