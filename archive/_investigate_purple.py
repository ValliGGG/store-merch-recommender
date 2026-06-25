"""Investigate the user's complaint:
   filter.p.m.custom.farba=fioletowa (purple) returns products that aren't purple."""
from urllib import request
import re, html as htmllib, json

u = "https://artmie.pl/collections/papier-i-arkusze-rysunkowe?filter.p.m.custom.farba=fioletowa&filter.v.availability=1&sort_by=manual"
print(f"Fetching: {u}")
h = request.urlopen(request.Request(u, headers={"User-Agent":"Mozilla/5.0"}), timeout=25).read().decode("utf-8", "replace")

# Pull first 5 product cards: handle + title
cards = re.findall(r'<product-card[^>]*data-product-id="(\d+)"[^>]*?(?:data-artmie-vsf="([^"]*)")?', h)
print(f"\nFound {len(cards)} product-cards on page")

# Pull each card's link to extract the product handle
links = re.findall(r'<a[^>]+href="(/products/[^"?#]+)"', h)
seen = []
for l in links:
    if l not in seen and '/products/' in l:
        seen.append(l)
print(f"Found {len(seen)} unique product links")

# Show first 5
for l in seen[:5]:
    print(f"  {l}")
