"""Append the search-redirect IIFE to artmie-filters-accordion.js on all 4 stores.
Idempotent — checks for the marker comment and skips if already present.
"""
import sys, os, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config
config.load()
from urllib import request, parse

MARKER = "/* ARTMIE_SEARCH_REDIRECT_v1 */"

# Read the search-redirect JS
js_path = Path(__file__).resolve().parent / "theme" / "artmie-search-redirect.js"
search_redirect_js = js_path.read_text(encoding="utf-8")

# Build the snippet to append — wrapped with marker so we can detect re-deploys
APPEND_BLOCK = f"\n\n{MARKER}\n{search_redirect_js}\n/* /ARTMIE_SEARCH_REDIRECT_v1 */\n"

ASSET_KEY = "assets/artmie-filters-accordion.js"

for store in ["SK", "PL", "BA", "MK"]:
    url = os.environ[f"ARTMIE_{store}_STORE_URL"]
    tok = os.environ[f"ARTMIE_{store}_API_TOKEN"]
    api = f"https://{url}/admin/api/2025-01"
    headers = {"X-Shopify-Access-Token": tok, "Content-Type": "application/json"}

    # Find main theme
    req = request.Request(f"{api}/themes.json", headers={"X-Shopify-Access-Token": tok})
    themes = json.loads(request.urlopen(req).read())["themes"]
    main = next(t for t in themes if t["role"] == "main")

    # Fetch existing asset
    qs = parse.urlencode({"asset[key]": ASSET_KEY})
    req = request.Request(f"{api}/themes/{main['id']}/assets.json?{qs}", headers={"X-Shopify-Access-Token": tok})
    existing = json.loads(request.urlopen(req).read())["asset"]["value"]

    if MARKER in existing:
        # Already deployed — strip and re-append (so updates take effect)
        before = existing.split(MARKER)[0].rstrip()
        new_value = before + APPEND_BLOCK
        action = "REPLACED existing block"
    else:
        new_value = existing.rstrip() + APPEND_BLOCK
        action = "appended"

    # PUT the updated asset
    body = json.dumps({"asset": {"key": ASSET_KEY, "value": new_value}}).encode("utf-8")
    req = request.Request(
        f"{api}/themes/{main['id']}/assets.json",
        data=body, method="PUT", headers=headers,
    )
    try:
        resp = json.loads(request.urlopen(req).read())
        print(f"{store}: {action}, new asset size = {len(new_value)} chars (theme {main['id']})")
    except Exception as e:
        print(f"{store}: ERROR {e}")
