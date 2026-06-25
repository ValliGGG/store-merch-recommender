from urllib import request
import re

handle = "artmie-lumina-fixative-spray-400-ml-pl-artfixlum"
test_urls = [
    f"https://artmie.pl/products/{handle}",                          # direct hit -> first collection / all
    f"https://artmie.pl/collections/promocje/products/{handle}",     # in-context -> /collections/promocje
    f"https://artmie.pl/collections/farby-artystyczne/products/{handle}",  # in-context -> /collections/farby-artystyczne
]

for u in test_urls:
    print(f"\n=== {u}")
    req = request.Request(u, headers={"User-Agent": "Mozilla/5.0 (Mobile)"})
    try:
        html = request.urlopen(req, timeout=20).read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"   FAIL fetch: {e}"); continue
    print(f"   JS marker present:    {'ARTMIE_BACKLINK_v1' in html}")
    print(f"   data-artmie-back:     {'data-artmie-back' in html}")
    m = re.search(r'<a[^>]*data-artmie-back[^>]*>', html)
    if m:
        tag = m.group(0)
        href = re.search(r'href="([^"]+)"', tag)
        print(f"   tag: {tag[:200]}")
        if href: print(f"   href = {href.group(1)}")
