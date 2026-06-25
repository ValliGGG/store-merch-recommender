"""Quick progress check: how many products remain in each promo collection."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig
cfg = cfg_mod.load()

PROMO = {"SK":"zlava", "PL":"promocje", "BA":"akcije", "MK":"popusti"}
Q = "query ($h:String!){ collectionByHandle(handle:$h){ handle productsCount{count} } }"

for code in ["SK","PL","BA","MK"]:
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    tok = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    if not url: continue
    shop = ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version)
    client = ShopifyClient(shop)
    d = client.execute(Q, {"h": PROMO[code]})
    c = d["collectionByHandle"]
    print(f"  {code}: {c['handle']:12s} = {c['productsCount']['count']} products")
