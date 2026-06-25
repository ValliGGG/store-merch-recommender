"""Decode HTML entities and find real multi-option payloads."""
from urllib import request
import re, html as htmllib

u = "https://artmie.pl/collections/farby-akrylowe"
htm = request.urlopen(request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read().decode("utf-8", "replace")
matches = re.findall(r'data-artmie-vsf="([^"]+)"', htm)
print(f"total cards: {len(matches)}")
multi = []
for m in matches:
    decoded = htmllib.unescape(m)
    if '"o":["title"]' not in decoded:
        multi.append(decoded)
print(f"multi-option (real): {len(multi)}")
for s in multi[:5]:
    print(f"\n  {s[:400]}")
