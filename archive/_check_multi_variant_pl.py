"""Find products that DO have multiple options on PL store."""
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

# Search for products with > 1 variant
Q = """
query {
  products(first: 30, query: "variants_count:>3") {
    edges { node {
      handle title
      options { name }
      totalVariants
      variants(first: 3) { edges { node { sku selectedOptions { name value } inventoryQuantity } } }
    } }
  }
}
"""
d = client.execute(Q, {})
for e in d["products"]["edges"][:10]:
    n = e["node"]
    opts = [o["name"] for o in n["options"]]
    print(f"\n  - {n['handle'][:55]}")
    print(f"      options={opts}  variants={n['totalVariants']}")
    for ve in n["variants"]["edges"][:3]:
        v = ve["node"]
        sopts = [(o['name'],o['value']) for o in v['selectedOptions']]
        print(f"      sku={(v['sku'] or 'n/a'):14s} inv={v.get('inventoryQuantity')}  {sopts}")
