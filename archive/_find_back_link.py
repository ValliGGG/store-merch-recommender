"""Find the 'Powrót do sklepu' / back-to-shop link in the PL theme."""
import os, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
cfg_mod.load()  # loads .env into os.environ
from urllib import request, parse

url = os.environ["ARTMIE_PL_STORE_URL"]
tok = os.environ["ARTMIE_PL_API_TOKEN"]
api = f"https://{url}/admin/api/2025-01"
H = {"X-Shopify-Access-Token": tok}

themes = json.loads(request.urlopen(request.Request(f"{api}/themes.json", headers=H)).read())["themes"]
main = next(t for t in themes if t["role"] == "main")
print(f"PL main theme: {main['id']}  '{main['name']}'")

assets = json.loads(request.urlopen(request.Request(f"{api}/themes/{main['id']}/assets.json", headers=H)).read())["assets"]
print(f"  total assets: {len(assets)}")

SEARCH_TERMS = ["Powrót do sklepu", "back_to_shop", "back-to-shop", "/collections/all", "Back to shop", "Powrót"]

for a in assets:
    key = a["key"]
    if not (key.endswith(".liquid") or key.endswith(".json") or key.endswith(".js")):
        continue
    qs = parse.urlencode({"asset[key]": key})
    try:
        body = json.loads(request.urlopen(request.Request(f"{api}/themes/{main['id']}/assets.json?{qs}", headers=H)).read())
    except Exception:
        continue
    val = body["asset"].get("value") or ""
    for term in SEARCH_TERMS:
        if term in val:
            for i, line in enumerate(val.splitlines(), 1):
                if term in line:
                    print(f"  HIT  {key}:{i}  [{term}]   {line.strip()[:160]}")
                    break  # only first hit per term per file
