import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig
cfg = cfg_mod.load()

PREFIXES = [
    ("BA", "slikarsko-platno-na-okviru-profi-artmie"),
    ("BA", "akvarel-boje-schmincke-horadam-pola-posudice"),
    ("MK", "akvarelna-boja-schmincke-horadam-polovina"),
]
Q = "query ($q:String!){ products(first:5, query:$q){ edges{ node{ handle title totalVariants } } } }"
for code, prefix in PREFIXES:
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    tok = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    shop = ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version)
    client = ShopifyClient(shop)
    d = client.execute(Q, {"q": f"handle:{prefix}*"})
    for e in d["products"]["edges"]:
        n = e["node"]
        print(f"  [{code}] {n['handle']}  ({n['totalVariants']} variants)  {n['title'][:40]}")
