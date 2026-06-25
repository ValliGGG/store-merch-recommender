"""Find first 3 products + their custom.farba metafield."""
from urllib import request
import re, html as htmllib, json
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig
cfg = cfg_mod.load()

u = "https://artmie.pl/collections/papier-i-arkusze-rysunkowe?filter.p.m.custom.farba=fioletowa&filter.v.availability=1&sort_by=manual"
h = request.urlopen(request.Request(u, headers={"User-Agent":"Mozilla/5.0"}), timeout=25).read().decode("utf-8", "replace")

# Find product handles via the canonical /products/HANDLE pattern
handles = []
for m in re.finditer(r'/products/([a-z0-9\-]{8,})', h):
    handle = m.group(1)
    if handle not in handles:
        handles.append(handle)
print(f"Found {len(handles)} unique handles, first 5:")
for hh in handles[:5]:
    print(f"   {hh}")

# Look up each via Admin API to inspect custom.farba metafield + variants
shop = ShopConfig(store_url=os.environ["ARTMIE_PL_STORE_URL"],
                  api_token=os.environ["ARTMIE_PL_API_TOKEN"],
                  api_version=cfg.shop.api_version)
client = ShopifyClient(shop)

Q = """
query ($h: String!) {
  productByHandle(handle: $h) {
    handle title featuredImage{url}
    options { name }
    variants(first: 10) { edges { node { sku selectedOptions { name value } inventoryQuantity } } }
    farba: metafield(namespace:"custom", key:"farba") { value type }
    farby: metafield(namespace:"custom", key:"farby") { value type }
    color: metafield(namespace:"custom", key:"color") { value type }
  }
}
"""
print("\n=== INSPECT FIRST 5 PRODUCTS ===")
for h in handles[:5]:
    d = client.execute(Q, {"h": h})
    p = d.get("productByHandle")
    if not p:
        print(f"\n[{h}] NOT FOUND"); continue
    print(f"\n[{h}]  title='{p['title'][:50]}'")
    print(f"   options: {[o['name'] for o in p['options']]}  variants: {len(p['variants']['edges'])}")
    for ve in p['variants']['edges'][:5]:
        v = ve['node']
        sopts = [(o['name'], o['value']) for o in v['selectedOptions']]
        print(f"     sku={v['sku'] or '?':14s} inv={v['inventoryQuantity']}  {sopts}")
    for k in ['farba', 'farby', 'color']:
        mf = p.get(k)
        if mf:
            print(f"   metafield {k}: type={mf['type']}  value={mf['value'][:120]}")
