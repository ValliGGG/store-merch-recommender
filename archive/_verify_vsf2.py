"""Find products with color/size options + verify a filter URL hides OOS variants."""
from urllib import request, error
import re

# Collection of brushes/markers usually has color and size variants
test_urls = [
    "https://artmie.pl/collections/papier-i-arkusze-rysunkowe",
    "https://artmie.pl/collections/farby-akrylowe?filter.v.option.color=czerwony",
    "https://artmie.pl/collections/farby-akrylowe?filter.v.availability=1",
]

for u in test_urls:
    print(f"\n=== {u}")
    try:
        html = request.urlopen(request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read().decode("utf-8", "replace")
    except error.HTTPError as e:
        print(f"   HTTP {e.code}"); continue
    except Exception as e:
        print(f"   FAIL {e}"); continue

    # Find a multi-option card
    matches = re.findall(r'data-artmie-vsf="([^"]+)"', html)
    multi = [m for m in matches if '"o":["title"]' not in m and len(m) > 80]
    print(f"   total cards: {len(matches)}  multi-option: {len(multi)}")
    if multi:
        s = multi[0].replace("&quot;", '"')[:300]
        print(f"   first multi-option payload:")
        print(f"     {s}")
