"""Fetch a live PL product page and extract the alternative-products card markup."""
from urllib import request
import re

handle = "artmie-lumina-fixative-spray-400-ml-pl-artfixlum"
u = f"https://artmie.pl/products/{handle}"
html = request.urlopen(request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read().decode("utf-8", "replace")

# Find the alternative-products section
m = re.search(r'<alternative-products[\s\S]*?</alternative-products>', html)
if not m:
    print("No alternative-products section found")
else:
    section = m.group(0)
    # Extract first card (first swiper-slide)
    sm = re.search(r'<div class="swiper-slide"[\s\S]*?</div>\s*</div>\s*</div>\s*</div>\s*</div>\s*</div>', section)
    if sm:
        card = sm.group(0)
    else:
        card = section[:8000]
    # Find all elements containing "koszyka" (case insensitive)
    print("=== KOSZYKA mentions in alt-products section ===")
    for i, line in enumerate(section.split("\n")):
        if "koszyka" in line.lower() or "KOSZYKA" in line:
            print(f"  L{i}: {line.strip()[:200]}")
    print("\n=== buy-buttons / add-to-cart elements ===")
    for tag in re.findall(r'<(?:button|add-to-cart-component|product-form|buy-buttons-component)[^>]*>', section):
        print(f"  {tag[:200]}")
    print(f"\nFirst card (~first 4500 chars):\n{card[:4500]}")
