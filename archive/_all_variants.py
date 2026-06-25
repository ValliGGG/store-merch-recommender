"""All 10 variants of the first product to see if a purple variant exists."""
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

handles = ["papier-barwiony-a4-rozne-kolory-fbcf64",
           "plynna-farba-tempera-jovi-500-ml-rozne-odcienie-jov506",
           "bibula-gladka-50-x-70-cm-25-szt-rozne-kolory-cch20"]

Q = """
query ($h:String!) {
  productByHandle(handle:$h) {
    handle title totalVariants
    variants(first: 250) {
      edges { node { sku selectedOptions{name value} inventoryQuantity } }
    }
    farba: metafield(namespace:"custom", key:"farba") { value }
  }
}
"""

for h in handles:
    d = client.execute(Q, {"h": h})
    p = d["productByHandle"]
    print(f"\n[{h}]  totalVariants={p['totalVariants']}")
    print(f"   metafield farba: {p['farba']['value'] if p['farba'] else None}")
    print(f"   ALL variants ({len(p['variants']['edges'])}):")
    purple_in_stock = []
    purple_oos = []
    for ve in p['variants']['edges']:
        v = ve['node']
        val = v['selectedOptions'][0]['value']
        inv = v['inventoryQuantity']
        marker = ""
        if "fiolet" in val.lower():
            marker = "  <-- PURPLE"
            if (inv or 0) > 0: purple_in_stock.append(val)
            else: purple_oos.append(val)
        print(f"     '{val}'  inv={inv}{marker}")
    print(f"   purple variants IN STOCK: {purple_in_stock}")
    print(f"   purple variants OOS:      {purple_oos}")
