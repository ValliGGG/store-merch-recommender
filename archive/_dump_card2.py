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

# Dump the rest of product-card-actions, plus product-card.liquid bottom half
for key in ["snippets/product-card-actions.liquid", "snippets/product-card.liquid"]:
    qs = parse.urlencode({"asset[key]": key})
    body = json.loads(request.urlopen(request.Request(f"{api}/themes/{main['id']}/assets.json?{qs}", headers=H)).read())
    val = body["asset"]["value"]
    print(f"\n=== {key} (last 3500 chars) ===")
    print(val[-3500:])
