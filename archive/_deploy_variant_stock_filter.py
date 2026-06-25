"""Deploy ARTMiE variant-aware stock filter across all 4 stores.

Three coordinated changes per store (idempotent):

1. assets/artmie-variant-stock-filter.js
   The classifier — pure DOM, no network. Reads URL filters,
   marks cards whose matching variant is OOS with data-artmie-vsf-oos="1".

2. snippets/product-card.liquid
   Adds data-artmie-vsf="<json>" to <product-card> ONLY on collection
   and search templates. Compact JSON: {"o":["color","size"], "v":[["red","10",1],...]}.
   Idempotent — replaces marker block if already present.

3. layout/theme.liquid (<head>)
   - Inline class-toggle (<200 bytes) sets html.artmie-vsf-active when URL
     has any filter.v.option.* param. CSS pre-hides marked cards instantly.
   - <script defer src=".../artmie-variant-stock-filter.js"> tag.
   Idempotent — wrapped in marker block.

4. assets/artmie-cards.css
   CSS rule that hides marked cards: keeps grid layout clean.
   Wrapped in marker block, idempotent.

Deploys to SK, PL, BA, MK with byte-identical assets.
"""
import os, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
cfg_mod.load()
from urllib import request, parse

ROOT = Path(__file__).resolve().parent

# ---------------- 1. JS asset ----------------
JS_PATH    = ROOT / "theme" / "artmie-variant-stock-filter.js"
JS_BODY    = JS_PATH.read_text(encoding="utf-8")
JS_KEY     = "assets/artmie-variant-stock-filter.js"

# ---------------- 1b. Multi-ATC redirect ----------------
ATC_JS_PATH = ROOT / "theme" / "artmie-card-multi-atc.js"
ATC_JS_BODY = ATC_JS_PATH.read_text(encoding="utf-8")
ATC_JS_KEY  = "assets/artmie-card-multi-atc.js"

# ---------------- 2. Liquid snippet patch ----------------
LIQUID_KEY = "snippets/product-card.liquid"

LIQUID_MARKER_BEGIN = "{%- comment -%} ARTMIE_VSF_v1 BEGIN {%- endcomment -%}"
LIQUID_MARKER_END   = "{%- comment -%} ARTMIE_VSF_v1 END {%- endcomment -%}"

# Liquid block that builds the compact variant data and emits the attribute.
# Only runs on collection / search / featured-collection contexts (anywhere
# customers filter by variant option). The {%- if vsf_data != blank -%} guard
# keeps onboarding/preview cards safe.
LIQUID_VSF_BLOCK = LIQUID_MARKER_BEGIN + """
{%- liquid
  assign vsf_emit = false
  if template contains 'collection' or template contains 'search'
    assign vsf_emit = true
  endif
  assign vsf_data = ''
  if vsf_emit and product != blank and product.variants.size > 0
    capture vsf_o
      for opt in product.options_with_values
        unless forloop.first
          echo ','
        endunless
        echo '"'
        echo opt.name | downcase | strip | replace: '"', '\\"'
        echo '"'
      endfor
    endcapture
    capture vsf_v
      for v in product.variants
        unless forloop.first
          echo ','
        endunless
        assign o1 = v.option1 | default: '' | downcase | strip | replace: '"', '\\"'
        assign o2 = v.option2 | default: '' | downcase | strip | replace: '"', '\\"'
        assign o3 = v.option3 | default: '' | downcase | strip | replace: '"', '\\"'
        echo '["'
        echo o1
        echo '","'
        echo o2
        echo '","'
        echo o3
        echo '",'
        if v.available
          echo '1'
        else
          echo '0'
        endif
        echo ']'
      endfor
    endcapture
    capture vsf_data
      echo '{"o":['
      echo vsf_o
      echo '],"v":['
      echo vsf_v
      echo ']}'
    endcapture
  endif
-%}
""" + LIQUID_MARKER_END

# Insertion point in Liquid: replace the <product-card opening tag.
# We keep all original attributes and inject data-artmie-vsf using {% if vsf_data %}.
LIQUID_FROM = '<product-card\n  class="product-card"\n  data-product-id="{{ product.id }}"'
LIQUID_TO   = ('<product-card\n  class="product-card"\n'
               '  {% if vsf_data != blank %}data-artmie-vsf="{{ vsf_data | escape }}"{% endif %}\n'
               '  data-product-id="{{ product.id }}"')

# ---------------- 3. theme.liquid head ----------------
THEME_KEY = "layout/theme.liquid"
HEAD_MARKER_BEGIN = "<!-- ARTMIE_VSF_v1 -->"
HEAD_MARKER_END   = "<!-- /ARTMIE_VSF_v1 -->"
HEAD_INJECTION = (
    f"\n  {HEAD_MARKER_BEGIN}\n"
    "  <script>(function(){if(location.search&&/[?&]filter\\.(v\\.option|p\\.m\\.)/i.test(location.search)){document.documentElement.classList.add('artmie-vsf-active');}})();</script>\n"
    "  {{ 'artmie-variant-stock-filter.js' | asset_url | script_tag }}\n"
    "  {{ 'artmie-card-multi-atc.js' | asset_url | script_tag }}\n"
    f"  {HEAD_MARKER_END}\n"
)

# ---------------- 4. CSS hide rule ----------------
CSS_KEY = "assets/artmie-cards.css"
CSS_MARKER_BEGIN = "/* === ARTMIE_VSF_HIDE_v1 === */"
CSS_MARKER_END   = "/* === /ARTMIE_VSF_HIDE_v1 === */"
CSS_BLOCK = f"""

{CSS_MARKER_BEGIN}
/* Hide product cards whose matching variant is out of stock when an
   option-level filter (color/size/etc.) is active. Marker is set by
   artmie-variant-stock-filter.js after parsing per-card variant data. */
html.artmie-vsf-active product-card[data-artmie-vsf-oos="1"] {{
  display: none !important;
}}
/* Hide unchecked filter chips that would yield zero in-stock results
   in the current collection (also set by artmie-variant-stock-filter.js).
   Independent of the active class — chips are pruned even when no
   filter is applied yet. */
[data-artmie-vsf-prune="1"] {{
  display: none !important;
}}
{CSS_MARKER_END}
"""


def fetch(api, theme_id, key, H):
    qs = parse.urlencode({"asset[key]": key})
    body = json.loads(request.urlopen(request.Request(
        f"{api}/themes/{theme_id}/assets.json?{qs}", headers=H)).read())
    return body["asset"]["value"]

def put(api, theme_id, key, value, tok):
    H = {"X-Shopify-Access-Token": tok, "Content-Type": "application/json"}
    body = json.dumps({"asset": {"key": key, "value": value}}).encode("utf-8")
    request.urlopen(request.Request(
        f"{api}/themes/{theme_id}/assets.json", data=body, method="PUT", headers=H)).read()

def strip_marker_block(text, begin, end):
    if begin in text and end in text:
        before = text.split(begin)[0].rstrip()
        after  = text.split(end, 1)[1].lstrip()
        return before + ("\n" if after else "") + after
    return text

def patch_liquid(existing):
    # 1. Strip any previous version of our liquid header block
    existing = strip_marker_block(existing, LIQUID_MARKER_BEGIN, LIQUID_MARKER_END)
    # 2. Strip any previous data-artmie-vsf injection inside <product-card>
    if 'data-artmie-vsf="' in existing:
        # remove the "{% if vsf_data %}data-artmie-vsf=..." line
        import re
        existing = re.sub(
            r'\s*\{% if vsf_data != blank %\}data-artmie-vsf="\{\{ vsf_data \| escape \}\}"\{% endif %\}\s*\n',
            "\n", existing)
    # 3. Insert fresh header block at top (just before {% assign block_settings %} or first {% liquid %})
    insert_pt = existing.find("{% assign block_settings = block.settings %}")
    if insert_pt < 0:
        insert_pt = existing.find("{% liquid")
    if insert_pt < 0:
        # fallback: prepend
        new_text = LIQUID_VSF_BLOCK + "\n\n" + existing
    else:
        new_text = existing[:insert_pt] + LIQUID_VSF_BLOCK + "\n\n" + existing[insert_pt:]
    # 4. Inject the data-artmie-vsf attribute into the <product-card> opening tag
    if LIQUID_FROM not in new_text:
        raise RuntimeError("Could not find <product-card> opening tag — aborting")
    new_text = new_text.replace(LIQUID_FROM, LIQUID_TO, 1)
    return new_text

def patch_theme_liquid(existing):
    existing = strip_marker_block(existing, HEAD_MARKER_BEGIN, HEAD_MARKER_END)
    head_idx = existing.lower().find("<head>")
    if head_idx < 0:
        raise RuntimeError("No <head> tag found in theme.liquid")
    insertion = head_idx + len("<head>")
    return existing[:insertion] + HEAD_INJECTION + existing[insertion:]

def patch_css(existing):
    existing = strip_marker_block(existing, CSS_MARKER_BEGIN, CSS_MARKER_END)
    return existing.rstrip() + CSS_BLOCK


for code in ["SK", "PL", "BA", "MK"]:
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    tok = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    if not url:
        print(f"[{code}] no env, skip"); continue
    api = f"https://{url}/admin/api/2025-01"
    H = {"X-Shopify-Access-Token": tok}
    themes = json.loads(request.urlopen(request.Request(f"{api}/themes.json", headers=H)).read())["themes"]
    main = next(t for t in themes if t["role"] == "main")
    print(f"\n[{code}] theme {main['id']} '{main['name']}'")

    # 1. JS asset
    put(api, main["id"], JS_KEY, JS_BODY, tok)
    print(f"   ✓ {JS_KEY} ({len(JS_BODY)} chars)")

    # 1b. Multi-variant ATC redirect
    put(api, main["id"], ATC_JS_KEY, ATC_JS_BODY, tok)
    print(f"   ✓ {ATC_JS_KEY} ({len(ATC_JS_BODY)} chars)")

    # 2. Liquid snippet
    liquid = fetch(api, main["id"], LIQUID_KEY, H)
    new_liquid = patch_liquid(liquid)
    put(api, main["id"], LIQUID_KEY, new_liquid, tok)
    print(f"   ✓ {LIQUID_KEY} ({len(liquid)} -> {len(new_liquid)} chars)")

    # 3. theme.liquid head
    theme = fetch(api, main["id"], THEME_KEY, H)
    new_theme = patch_theme_liquid(theme)
    put(api, main["id"], THEME_KEY, new_theme, tok)
    print(f"   ✓ {THEME_KEY} ({len(theme)} -> {len(new_theme)} chars)")

    # 4. CSS hide rule
    css = fetch(api, main["id"], CSS_KEY, H)
    new_css = patch_css(css)
    put(api, main["id"], CSS_KEY, new_css, tok)
    print(f"   ✓ {CSS_KEY} ({len(css)} -> {len(new_css)} chars)")

print("\nDONE — variant-stock filter deployed across all stores.")
