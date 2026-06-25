"""Fetch the AJAX response Shopify sends when a filter changes,
inspect whether product-card data-artmie-vsf is preserved."""
from urllib import request
import re

# Two ways Shopify renders for filter AJAX:
# 1. ?section_id=collection-product-grid (typical)
# 2. ?_=1234 (just sometimes)
# Try a couple of common patterns
candidates = [
    # Full page (baseline) — should have data-artmie-vsf
    "https://artmie.pl/collections/papier-i-arkusze-rysunkowe?filter.p.m.custom.farba=fioletowa&filter.v.availability=1",
    # Section-only renders that Search & Discovery uses
    "https://artmie.pl/collections/papier-i-arkusze-rysunkowe?filter.p.m.custom.farba=fioletowa&filter.v.availability=1&section_id=main-collection-product-grid",
    "https://artmie.pl/collections/papier-i-arkusze-rysunkowe?filter.p.m.custom.farba=fioletowa&filter.v.availability=1&section_id=facets-results",
    "https://artmie.pl/collections/papier-i-arkusze-rysunkowe?filter.p.m.custom.farba=fioletowa&filter.v.availability=1&section_id=product-grid",
]

for u in candidates:
    print(f"\n=== {u}")
    try:
        h = request.urlopen(request.Request(u, headers={"User-Agent":"Mozilla/5.0", "Accept":"text/html"}), timeout=15).read().decode("utf-8","replace")
    except Exception as e:
        print(f"   FAIL {e}"); continue
    n_cards = len(re.findall(r'<product-card\b', h))
    n_vsf = len(re.findall(r'data-artmie-vsf="', h))
    has_marker = "ARTMIE_VSF_v1" in h
    print(f"   length: {len(h):>7} chars  product-cards: {n_cards}  data-artmie-vsf attrs: {n_vsf}  head_marker: {has_marker}")

# Also fetch the actual section_id used by the live theme
# The Shopify storefront filter library inspects DOM for [data-section-id] attribute.
print("\n=== Sniffing live page for section_id ===")
h = request.urlopen(request.Request("https://artmie.pl/collections/papier-i-arkusze-rysunkowe", headers={"User-Agent":"Mozilla/5.0"}), timeout=15).read().decode("utf-8","replace")
sec_ids = set()
for m in re.finditer(r'data-section(?:-id)?="([^"]+)"', h):
    sec_ids.add(m.group(1))
for m in re.finditer(r'id="(?:Shopify|shopify)-section-([^"]+)"', h):
    sec_ids.add(m.group(1))
print(f"  found section ids: {sorted(sec_ids)[:20]}")
