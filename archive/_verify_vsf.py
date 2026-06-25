"""Verify the variant-stock filter is live on PL collection page."""
from urllib import request, error
import re

# Pick a collection that has color-filterable products
test_urls = [
    "https://artmie.pl/collections/farby-akrylowe",
    "https://artmie.pl/collections/promocje",
]

for u in test_urls:
    print(f"\n=== {u}")
    try:
        html = request.urlopen(request.Request(u, headers={"User-Agent": "Mozilla/5.0 (Mobile)"}), timeout=20).read().decode("utf-8", "replace")
    except error.HTTPError as e:
        print(f"   HTTP {e.code}"); continue
    except Exception as e:
        print(f"   FAIL {e}"); continue

    # Inline head script present?
    has_inline = "ARTMIE_VSF_v1" in html
    has_class_setter = "artmie-vsf-active" in html
    has_js = "artmie-variant-stock-filter.js" in html
    has_data = 'data-artmie-vsf="' in html
    n_cards = len(re.findall(r'<product-card\b', html))
    n_data_cards = len(re.findall(r'data-artmie-vsf="', html))
    print(f"   inline head marker: {has_inline}")
    print(f"   class-setter present: {has_class_setter}")
    print(f"   classifier JS link: {has_js}")
    print(f"   product-card count: {n_cards}")
    print(f"   cards with data-artmie-vsf: {n_data_cards}")
    if has_data:
        # Pull out one sample data-artmie-vsf payload
        m = re.search(r'data-artmie-vsf="([^"]{20,400})"', html)
        if m:
            sample = m.group(1).replace("&quot;", '"')[:240]
            print(f"   sample data: {sample}")
