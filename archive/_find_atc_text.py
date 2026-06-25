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
assets = json.loads(request.urlopen(request.Request(f"{api}/themes/{main['id']}/assets.json", headers=H)).read())["assets"]

TERMS = ["add-to-cart-text__content", "add-to-cart-text", "BuyButtons-ProductSubmitButton",
         "add-to-cart-button", "buy-buttons-block", "_buy-buttons", "buy_buttons"]
for a in assets:
    key = a["key"]
    if not (key.endswith(".liquid") or key.endswith(".css") or key.endswith(".js") or key.endswith(".json")):
        continue
    qs = parse.urlencode({"asset[key]": key})
    try:
        body = json.loads(request.urlopen(request.Request(f"{api}/themes/{main['id']}/assets.json?{qs}", headers=H)).read())
    except: continue
    val = body["asset"].get("value") or ""
    for term in TERMS:
        if term in val:
            for i, line in enumerate(val.splitlines(), 1):
                if term in line:
                    print(f"  {key}:{i}  [{term}]   {line.strip()[:160]}")
                    break
