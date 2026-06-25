"""Inject the search-redirect script INLINE into layout/theme.liquid for all 4 stores.

Inline placement: immediately after <head> opening tag so it runs first,
before any content renders. No extra HTTP request, < 2KB payload.

Idempotent — finds the marker and replaces if already present.
"""
import sys, os, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config
config.load()
from urllib import request, parse

MARKER_BEGIN = "<!-- ARTMIE_SEARCH_REDIRECT_v1 -->"
MARKER_END   = "<!-- /ARTMIE_SEARCH_REDIRECT_v1 -->"

js_path = Path(__file__).resolve().parent / "theme" / "artmie-search-redirect.js"
js_body = js_path.read_text(encoding="utf-8")

INJECTION = (
    f"\n  {MARKER_BEGIN}\n"
    f"  <script>\n{js_body}\n  </script>\n"
    f"  {MARKER_END}\n"
)

THEME_KEY = "layout/theme.liquid"

for store in ["SK", "PL", "BA", "MK"]:
    url = os.environ[f"ARTMIE_{store}_STORE_URL"]
    tok = os.environ[f"ARTMIE_{store}_API_TOKEN"]
    api = f"https://{url}/admin/api/2025-01"
    headers_get = {"X-Shopify-Access-Token": tok}
    headers_put = {"X-Shopify-Access-Token": tok, "Content-Type": "application/json"}

    # Find main theme
    req = request.Request(f"{api}/themes.json", headers=headers_get)
    main = next(t for t in json.loads(request.urlopen(req).read())["themes"] if t["role"] == "main")

    # Fetch theme.liquid
    qs = parse.urlencode({"asset[key]": THEME_KEY})
    req = request.Request(f"{api}/themes/{main['id']}/assets.json?{qs}", headers=headers_get)
    existing = json.loads(request.urlopen(req).read())["asset"]["value"]

    # Strip any previous version of our block
    if MARKER_BEGIN in existing and MARKER_END in existing:
        before = existing.split(MARKER_BEGIN)[0]
        after  = existing.split(MARKER_END, 1)[1]
        existing = before.rstrip() + after.lstrip()

    # Find <head> and inject right after it
    head_idx = existing.lower().find("<head>")
    if head_idx < 0:
        print(f"{store}: ERROR — no <head> found in theme.liquid")
        continue
    insertion_point = head_idx + len("<head>")
    new_value = existing[:insertion_point] + INJECTION + existing[insertion_point:]

    # PUT
    body = json.dumps({"asset": {"key": THEME_KEY, "value": new_value}}).encode("utf-8")
    req = request.Request(f"{api}/themes/{main['id']}/assets.json", data=body, method="PUT", headers=headers_put)
    try:
        request.urlopen(req).read()
        print(f"{store}: injected ({len(new_value)} chars total) into theme {main['id']}")
    except Exception as e:
        print(f"{store}: ERROR {e}")
