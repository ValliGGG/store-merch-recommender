"""Verify SK variant data + identify a real multi-variant product."""
from urllib import request
import re, html as htmllib, json

# Sample several SK collections
test_urls = [
    "https://app.artmie.sk/collections/akrylove-farby",
    "https://app.artmie.sk/collections/all",
    "https://app.artmie.sk/collections/zlava",
]

for u in test_urls:
    print(f"\n=== {u}")
    try:
        h = request.urlopen(request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read().decode("utf-8", "replace")
    except Exception as e:
        print(f"   FAIL {e}"); continue
    matches = re.findall(r'data-artmie-vsf="([^"]+)"', h)
    multi = []
    for m in matches:
        decoded = htmllib.unescape(m)
        try:
            data = json.loads(decoded)
            opts = data.get("o", [])
            if not (len(opts) == 1 and opts[0].lower() == "title"):
                multi.append(decoded)
        except: pass
    print(f"   total cards: {len(matches)}  real multi-option: {len(multi)}")
    for s in multi[:3]:
        d = json.loads(s)
        print(f"   options={d['o']}  variants={len(d['v'])}  in-stock={sum(1 for v in d['v'] if v[3]==1)}/total")
        # Show first 3 variants
        for v in d['v'][:3]:
            print(f"     {v}")
