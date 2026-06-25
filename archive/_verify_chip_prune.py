"""Simulate the prune logic on the user's collection."""
from urllib import request
import json, unicodedata

def normalize(s):
    if not s: return ""
    s = str(s).lower().strip()
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

# Fetch the collection's products
in_stock_values = set()
total_products = 0
total_variants_in_stock = 0
for page in range(1, 5):
    u = f"https://artmie.pl/collections/farby-do-powierzchni/products.json?limit=250&page={page}"
    try:
        r = request.urlopen(request.Request(u, headers={"User-Agent":"Mozilla/5.0"}), timeout=20)
        data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"page {page} fail: {e}"); break
    if not data.get("products"): break
    for p in data["products"]:
        total_products += 1
        for v in p.get("variants", []):
            if v.get("available"):
                total_variants_in_stock += 1
                for k in ("option1","option2","option3"):
                    if v.get(k): in_stock_values.add(normalize(v[k]))
    if len(data["products"]) < 250: break

print(f"Collection: farby-do-powierzchni")
print(f"  total products: {total_products}")
print(f"  in-stock variants: {total_variants_in_stock}")
print(f"  unique in-stock values: {len(in_stock_values)}")
print(f"\nFirst 30 in-stock values (normalized):")
for v in sorted(in_stock_values)[:30]:
    print(f"  {v}")

# Test specific colors
print(f"\n--- Test: would 'bronzova' be pruned? ---")
fv = normalize("bronzová")
print(f"  filter value normalized: '{fv}'")
matches = [v for v in in_stock_values if fv in v]
print(f"  in-stock values containing it: {matches}")
print(f"  decision: {'KEEP visible' if matches else 'HIDE chip'}")

# Test other colors
for color in ["czerwona", "fioletowa", "żółta", "niebieska", "biała"]:
    fv = normalize(color)
    matches = [v for v in in_stock_values if fv in v]
    print(f"  '{color}' (norm '{fv}'): {len(matches)} matches  -> {'keep' if matches else 'HIDE'}")
