"""Get one real PL product handle from the promocje collection."""
import os, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
cfg_mod.load()
from lib.shopify_client import ShopifyClient, ShopConfig
cfg = cfg_mod.load()

shop = ShopConfig(store_url=os.environ["ARTMIE_PL_STORE_URL"],
                  api_token=os.environ["ARTMIE_PL_API_TOKEN"],
                  api_version=cfg.shop.api_version)
client = ShopifyClient(shop)

q = """
query {
  collectionByHandle(handle:"promocje") {
    products(first:3) { edges { node { handle title } } }
  }
}"""
d = client.execute(q, {})
for e in d["collectionByHandle"]["products"]["edges"]:
    print(e["node"]["handle"], "—", e["node"]["title"][:50])
