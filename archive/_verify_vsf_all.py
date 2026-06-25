"""Verify VSF data on BA and MK (public) + check PL products with rich options."""
from urllib import request
import re, html as htmllib, json

# Test on BA + MK + PL (look for genuinely multi-option products)
test = {
    "BA": ["https://artmie.ba/collections/akrilne-boje", "https://artmie.ba/collections/akcije"],
    "MK": ["https://artmie.mk/collections/umetnichki-boi"],
    "PL": ["https://artmie.pl/collections/markery-i-flamastry", "https://artmie.pl/collections/farby-akwarelowe"],
}

for store, urls in test.items():
    print(f"\n========== {store} ==========")
    for u in urls:
        print(f"\n=== {u}")
        try:
            h = request.urlopen(request.Request(u, headers={"User-Agent":"Mozilla/5.0"}), timeout=25).read().decode("utf-8", "replace")
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
                    multi.append((decoded, data))
            except: pass
        print(f"   cards: {len(matches)}  multi-opt: {len(multi)}")
        for decoded, d in multi[:3]:
            in_stock = sum(1 for v in d['v'] if v[3]==1)
            total = len(d['v'])
            print(f"     options={d['o']}  variants={total}  in-stock={in_stock}/{total}")
