"""Deploy "Back to shop" smart-link fix to all 4 ARTMiE stores.

Three changes per store (idempotent):
  1. snippets/custom-pdp-breadcrumbs.liquid       — replace hardcoded all-products href
  2. snippets/product-information-breadcrumbs.liquid — add in-context `collection` priority
  3. layout/theme.liquid                          — inject inline JS that hijacks data-artmie-back
"""
import os, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
cfg_mod.load()
from urllib import request, parse

JS_MARKER_BEGIN = "<!-- ARTMIE_BACKLINK_v1 -->"
JS_MARKER_END   = "<!-- /ARTMIE_BACKLINK_v1 -->"
JS_BODY = (Path(__file__).resolve().parent / "theme" / "artmie-back-link.js").read_text(encoding="utf-8")

INJECTION = (
    f"\n  {JS_MARKER_BEGIN}\n"
    f"  <script>\n{JS_BODY}\n  </script>\n"
    f"  {JS_MARKER_END}\n"
)

# --- Custom snippet: full rewrite with smart back_url + data-artmie-back ---
CUSTOM_SNIPPET_NEW = '''{%- doc -%}
  Renders breadcrumbs, back button, and SKU for custom PDP

  @param {product} product - Product Liquid object
  @param {variant} selected_variant - Selected variant object
{%- enddoc -%}

{%- liquid
  # Use Product Breadcrumbs Collection metafield if available
  assign breadcrumb_collection = product.metafields.custom.product_breadcrumbs_collection.value
  if breadcrumb_collection == blank and product.collections.size > 0
    assign breadcrumb_collection = product.collections.first
  endif

  # Smart back URL: prefer the in-context collection (came from /collections/X/products/Y),
  # then the metafield/first collection, else fall back to all products.
  assign back_url = routes.all_products_collection_url
  if collection != blank and collection.url != blank
    assign back_url = collection.url
  elsif breadcrumb_collection != blank and breadcrumb_collection.url != blank
    assign back_url = breadcrumb_collection.url
  endif
-%}

<div class="custom-pdp-section__breadcrumbs">
  {%- comment -%} Desktop: Breadcrumbs {%- endcomment -%}
  <div class="custom-pdp-section__breadcrumbs-desktop">
    {%- render 'breadcrumbs', product: product, collection: breadcrumb_collection -%}
  </div>

  {%- comment -%} Mobile: Back to Shop Button {%- endcomment -%}
  <a href="{{ back_url }}" data-artmie-back="1" class="custom-pdp-section__back-button">
    {% render 'icons', icon: 'arrow-left-outlined' %}
    <span>{{ 'sections.product.back_to_shop' | t }}</span>
  </a>

  {%- if selected_variant.sku != blank -%}
    <span class="custom-pdp-section__sku">{{ selected_variant.sku }}</span>
  {%- endif -%}
</div>
'''

# --- Built-in snippet: minimal patch — add `collection` priority to back_url + data-artmie-back ---
BUILTIN_SNIPPET_NEW = '''{%- doc -%}
  Renders breadcrumbs and SKU row for the product-information section

  @param {product} product - Product Liquid object
  @param {variant} selected_variant - Currently selected variant
  @param {boolean} show_breadcrumbs - Whether to show breadcrumbs navigation
  @param {boolean} show_sku - Whether to show the product variant SKU

  @example
  {%- render 'product-information-breadcrumbs',
    product: closest.product,
    selected_variant: selected_variant,
    show_breadcrumbs: section.settings.show_breadcrumbs,
    show_sku: section.settings.show_sku
  -%}
{%- enddoc -%}

{%- liquid
  assign breadcrumb_collection = product.metafields.custom.product_breadcrumbs_collection.value
  if breadcrumb_collection == blank and product.collections.size > 0
    assign breadcrumb_collection = product.collections.first
  endif

  assign back_url = routes.all_products_collection_url
  if collection != blank and collection.url != blank
    assign back_url = collection.url
  elsif breadcrumb_collection != blank and breadcrumb_collection.url != blank
    assign back_url = breadcrumb_collection.url
  endif
-%}

<div class="product-information-breadcrumbs">
  {%- if show_breadcrumbs -%}
    <a href="{{- back_url -}}" data-artmie-back="1" class="product-information-breadcrumbs__back-button">
      {%- render 'icons', icon: 'arrow-left-outlined' -%}
      <span>{{- 'sections.product.back_to_shop' | t -}}</span>
    </a>
    {%- render 'breadcrumbs', product: product, collection: breadcrumb_collection, template: template -%}
  {%- endif -%}

  {%- if show_sku -%}
    <span
      class="product-information-breadcrumbs__sku{% if selected_variant.sku == blank %} hidden{% endif %}"
      data-product-sku
    >
      {{- selected_variant.sku -}}
    </span>
  {%- endif -%}
</div>
'''

THEME_KEY = "layout/theme.liquid"

def fetch(api, theme_id, key, H):
    qs = parse.urlencode({"asset[key]": key})
    body = json.loads(request.urlopen(request.Request(
        f"{api}/themes/{theme_id}/assets.json?{qs}", headers=H)).read())
    return body["asset"]["value"]

def put(api, theme_id, key, value, tok):
    H = {"X-Shopify-Access-Token": tok, "Content-Type": "application/json"}
    body = json.dumps({"asset": {"key": key, "value": value}}).encode("utf-8")
    req = request.Request(f"{api}/themes/{theme_id}/assets.json", data=body, method="PUT", headers=H)
    request.urlopen(req).read()

def maybe_write(api, theme_id, key, new_value, tok, label):
    H = {"X-Shopify-Access-Token": tok}
    try:
        existing = fetch(api, theme_id, key, H)
    except Exception as e:
        print(f"   {label}: SKIP (no asset / {e})"); return
    if existing.strip() == new_value.strip():
        print(f"   {label}: unchanged"); return
    put(api, theme_id, key, new_value, tok)
    print(f"   {label}: updated ({len(new_value)} chars)")

def inject_theme_liquid(api, theme_id, tok):
    H = {"X-Shopify-Access-Token": tok}
    val = fetch(api, theme_id, THEME_KEY, H)
    # Strip any previous version
    if JS_MARKER_BEGIN in val and JS_MARKER_END in val:
        before = val.split(JS_MARKER_BEGIN)[0]
        after  = val.split(JS_MARKER_END, 1)[1]
        val = before.rstrip() + after.lstrip()
    head_idx = val.lower().find("<head>")
    if head_idx < 0:
        print(f"   theme.liquid: ERROR — no <head> found"); return
    insertion = head_idx + len("<head>")
    new = val[:insertion] + INJECTION + val[insertion:]
    put(api, theme_id, THEME_KEY, new, tok)
    print(f"   theme.liquid: injected back-link JS ({len(new)} chars total)")

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
    maybe_write(api, main["id"], "snippets/custom-pdp-breadcrumbs.liquid",     CUSTOM_SNIPPET_NEW,  tok, "custom-pdp-breadcrumbs")
    maybe_write(api, main["id"], "snippets/product-information-breadcrumbs.liquid", BUILTIN_SNIPPET_NEW, tok, "product-information-breadcrumbs")
    inject_theme_liquid(api, main["id"], tok)

print("\nDONE — back-link fix deployed across all stores.")
