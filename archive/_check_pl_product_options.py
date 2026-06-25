"""Check what option structure PL products use."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig
cfg = cfg_mod.load()

shop = ShopConfig(store_url=os.environ["ARTMIE_PL_STORE_URL"],
                  api_token=os.environ["ARTMIE_PL_API_TOKEN"],
                  api_version=cfg.shop.api_version)
client = ShopifyClient(shop)

# Sample products from a few collections
Q = """
query ($cursor: String) {
  products(first: 30, after: $cursor, query: "vendor:Kreul OR vendor:ARTMIE OR product_type:'Akrylové farby'") {
    edges { node {
      handle title
      options { name }
      totalVariants
      variants(first: 3) { edges { node { sku selectedOptions { name value } inventoryQuantity } } }
    } }
  }
}
"""
d = client.execute(Q, {"cursor": None})
multi_opt = []
single_opt = []
for e in d["products"]["edges"]:
    n = e["node"]
    opts = [o["name"] for o in n["options"]]
    if len(opts) == 1 and opts[0].lower() == "title":
        single_opt.append(n)
    else:
        multi_opt.append(n)

print(f"Sampled {len(d['products']['edges'])} PL products")
print(f"  Single-variant ('Title'): {len(single_opt)}")
print(f"  Multi-option:             {len(multi_opt)}")
print(f"\nMulti-option sample:")
for n in multi_opt[:5]:
    print(f"  - {n['handle'][:55]} options={[o['name'] for o in n['options']]} variants={n['totalVariants']}")
    for ve in n["variants"]["edges"][:2]:
        v = ve["node"]
        print(f"      sku={v['sku']:14s} inv={v.get('inventoryQuantity')}  {[(o['name'],o['value']) for o in v['selectedOptions']]}")

print(f"\nSingle-variant sample:")
for n in single_opt[:5]:
    print(f"  - {n['handle'][:55]} variants={n['totalVariants']}")
