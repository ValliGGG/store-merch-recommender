"""Fix the duplicate add-to-cart button on alternative/recommended/recently-viewed
product cards (mobile only).

Three section CSS files each force `.add-to-cart-button { display: block; }` on mobile,
but artmie-cards.css already renders our branded `.product-card-actions__button--cart`
at the bottom of every product card. Result: two stacked buttons on mobile.

Solution: append an override block to artmie-cards.css that always hides the
Horizon native `.add-to-cart-button` inside our 3 carousel sections.
Idempotent — strips any previous version of our marker block first.
"""
import os, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
cfg_mod.load()
from urllib import request, parse

MARKER_BEGIN = "/* === ARTMIE_NO_DUP_ATC_v1 === */"
MARKER_END   = "/* === /ARTMIE_NO_DUP_ATC_v1 === */"

OVERRIDE_BLOCK = f"""

{MARKER_BEGIN}
/* Hide Horizon's native bottom 'Add to cart' button inside our 3 custom carousels.
   Our .product-card-actions__button--cart (Sephora-style) is the canonical CTA.
   Without this override, mobile shows two stacked add-to-cart buttons per card. */
.alternative-products .add-to-cart-button,
.recommended-products .add-to-cart-button,
.recently-viewed-products .add-to-cart-button {{
  display: none !important;
}}
{MARKER_END}
"""

ASSET_KEY = "assets/artmie-cards.css"

def fetch(api, theme_id, key, H):
    qs = parse.urlencode({"asset[key]": key})
    body = json.loads(request.urlopen(request.Request(f"{api}/themes/{theme_id}/assets.json?{qs}", headers=H)).read())
    return body["asset"]["value"]

def put(api, theme_id, key, value, tok):
    H = {"X-Shopify-Access-Token": tok, "Content-Type": "application/json"}
    body = json.dumps({"asset": {"key": key, "value": value}}).encode("utf-8")
    request.urlopen(request.Request(f"{api}/themes/{theme_id}/assets.json", data=body, method="PUT", headers=H)).read()

for code in ["SK", "PL", "BA", "MK"]:
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    tok = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    if not url:
        print(f"[{code}] no env, skip"); continue
    api = f"https://{url}/admin/api/2025-01"
    H = {"X-Shopify-Access-Token": tok}
    themes = json.loads(request.urlopen(request.Request(f"{api}/themes.json", headers=H)).read())["themes"]
    main = next(t for t in themes if t["role"] == "main")
    print(f"[{code}] theme {main['id']} '{main['name']}'")
    try:
        css = fetch(api, main["id"], ASSET_KEY, H)
    except Exception as e:
        print(f"   ! cannot fetch {ASSET_KEY}: {e}"); continue
    # Strip old version if present
    if MARKER_BEGIN in css and MARKER_END in css:
        before = css.split(MARKER_BEGIN)[0].rstrip()
        after  = css.split(MARKER_END, 1)[1].lstrip()
        css = before + ("\n" if after else "") + after
    new_css = css.rstrip() + OVERRIDE_BLOCK
    if new_css == css:
        print("   (no change)"); continue
    put(api, main["id"], ASSET_KEY, new_css, tok)
    print(f"   updated artmie-cards.css ({len(new_css)} chars)")

print("\nDONE — duplicate ATC button override deployed across all stores.")
