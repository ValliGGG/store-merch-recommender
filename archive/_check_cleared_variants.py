"""Sample variants in promo collection — count how many have null/0 compareAtPrice
(= script already cleared them; smart collection just hasn't reindexed yet)."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig
cfg = cfg_mod.load()

PROMO = {"SK":"zlava", "PL":"promocje", "BA":"akcije", "MK":"popusti"}
FIND_Q = "query ($h:String!){ collectionByHandle(handle:$h){ id handle } }"
Q = """
query ($id: ID!, $cursor: String) {
  collection(id: $id) {
    products(first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node {
        variants(first: 100) { edges { node { compareAtPrice price } } }
      } }
    }
  }
}
"""

for code in ["SK","PL","BA"]:
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    tok = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    if not url: continue
    shop = ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version)
    client = ShopifyClient(shop)
    d = client.execute(FIND_Q, {"h": PROMO[code]})
    coll_id = d["collectionByHandle"]["id"]

    # Walk first 200 products, count variants by compareAt state
    null_ca = 0; pos_ca = 0; real_sale = 0
    cursor = None; page = 0
    while page < 4:  # cap at 4 pages = 400 products max for speed
        d = client.execute(Q, {"id": coll_id, "cursor": cursor})
        c = d["collection"]
        for e in c["products"]["edges"]:
            for ve in e["node"]["variants"]["edges"]:
                v = ve["node"]
                ca = v.get("compareAtPrice")
                try: p = float(v.get("price") or 0)
                except: p = 0
                if ca is None or float(ca) == 0:
                    null_ca += 1
                else:
                    if float(ca) > p: real_sale += 1
                    else: pos_ca += 1
        pi = c["products"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]; page += 1

    total = null_ca + pos_ca + real_sale
    print(f"  {code}: sampled {total:5d} variants — null/0 compareAt: {null_ca:5d}  "
          f"compareAt>0 (still set): {pos_ca:5d}  real-sale (ca>p): {real_sale:5d}")
