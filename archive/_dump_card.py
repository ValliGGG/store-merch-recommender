import os, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
cfg_mod.load()
from urllib import request, parse

url = os.environ["ARTMIE_PL_STORE_URL"]
tok = os.environ["ARTMIE_PL_API_TOKEN"]
api = f"https://{url}/admin/api/2025-01"
H = {"X-Shopify-Access-Token": tok}
themes = json.loads(request.urlopen(request.Request(f"{api}/themes.json", headers=H)).read())["themes"]
main = next(t for t in themes if t["role"] == "main")

for key in ["snippets/product-card.liquid", "snippets/product-card-actions.liquid",
            "blocks/_product-card.liquid", "blocks/product-card.liquid"]:
    qs = parse.urlencode({"asset[key]": key})
    try:
        body = json.loads(request.urlopen(request.Request(f"{api}/themes/{main['id']}/assets.json?{qs}", headers=H)).read())
        print(f"\n=== {key} ({len(body['asset']['value'])} chars) ===")
        print(body["asset"]["value"][:6000])
    except Exception as e:
        print(f"\n=== {key} : NOT FOUND ({e}) ===")
