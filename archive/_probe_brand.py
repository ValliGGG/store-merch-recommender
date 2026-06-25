"""Probe one ARTMiE SK product to find where 'brand' is stored.

Checks: vendor, productType, tags, and ALL metafields on a sample product
(picked by handle pattern) plus aggregate counts across the catalog.
"""
import json, os, sys, time
from pathlib import Path
from urllib import request as urlreq, error as urlerr

ENV = Path(r"C:/Users/Valerian/Desktop/Claude 1TEST/shopify-reports/.env")
for line in ENV.read_text(encoding="utf-8").splitlines():
    if line.startswith("ARTMIE_SK_"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

SHOP = os.environ["ARTMIE_SK_STORE_URL"]
TOKEN = os.environ["ARTMIE_SK_API_TOKEN"]
URL = f"https://{SHOP}/admin/api/2025-01/graphql.json"

def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urlreq.Request(URL, data=body, method="POST", headers={
        "X-Shopify-Access-Token": TOKEN,
        "Content-Type": "application/json",
    })
    with urlreq.urlopen(req, timeout=60) as r:
        return json.loads(r.read())

# 1. Pull 3 products with ALL metafields visible
SAMPLE_Q = """
{
  products(first: 5, query: "vendor:Artmie") {
    edges {
      node {
        id
        legacyResourceId
        handle
        title
        vendor
        productType
        tags
        metafields(first: 50) {
          edges {
            node {
              namespace
              key
              type
              value
            }
          }
        }
      }
    }
  }
}
"""

print("=" * 80)
print("STEP 1: Sample 5 Artmie products with all metafields")
print("=" * 80)
data = gql(SAMPLE_Q)
if "errors" in data:
    print("GraphQL errors:", data["errors"])
    sys.exit(1)

for edge in data["data"]["products"]["edges"]:
    p = edge["node"]
    print(f"\n--- {p['title'][:60]} ---")
    print(f"  handle:      {p['handle']}")
    print(f"  vendor:      {p['vendor']!r}")
    print(f"  productType: {p['productType']!r}")
    print(f"  tags:        {p['tags']}")
    mfs = p["metafields"]["edges"]
    if not mfs:
        print("  metafields:  (none)")
    else:
        print(f"  metafields ({len(mfs)}):")
        for mf in mfs:
            n = mf["node"]
            val = n["value"]
            if len(val) > 80:
                val = val[:77] + "..."
            print(f"    {n['namespace']}.{n['key']:30s} ({n['type']:30s}) = {val!r}")

# 2. Aggregate vendor distribution (small page is enough)
print("\n" + "=" * 80)
print("STEP 2: Vendor distribution (first 250)")
print("=" * 80)
VENDOR_Q = """
{
  products(first: 250) {
    edges {
      node { vendor tags }
    }
  }
}
"""
data2 = gql(VENDOR_Q)
from collections import Counter
vendors = Counter()
brand_tags = Counter()
for e in data2["data"]["products"]["edges"]:
    v = e["node"]["vendor"]
    vendors[v] += 1
    for t in (e["node"]["tags"] or []):
        if t.lower().startswith("brand:") or t.lower() == "artmie":
            brand_tags[t] += 1

print("\nTop vendors (first 250 products):")
for v, n in vendors.most_common(15):
    print(f"  {n:5d}  {v!r}")

print("\nBrand-related tags found:")
if brand_tags:
    for t, n in brand_tags.most_common():
        print(f"  {n:5d}  {t!r}")
else:
    print("  (none)")

# 3. Check standard shopify.brand metafield definition existence
print("\n" + "=" * 80)
print("STEP 3: Look for shopify.brand standard metafield definition")
print("=" * 80)
DEF_Q = """
{
  metafieldDefinitions(first: 50, ownerType: PRODUCT, namespace: "shopify") {
    edges { node { namespace key name type { name } } }
  }
  customDefs: metafieldDefinitions(first: 50, ownerType: PRODUCT, namespace: "custom") {
    edges { node { namespace key name type { name } } }
  }
}
"""
data3 = gql(DEF_Q)
print("\nshopify.* product metafield definitions:")
for e in data3["data"]["metafieldDefinitions"]["edges"]:
    n = e["node"]
    print(f"  {n['namespace']}.{n['key']:30s} [{n['type']['name']}]  {n['name']!r}")

print("\ncustom.* product metafield definitions:")
for e in data3["data"]["customDefs"]["edges"]:
    n = e["node"]
    print(f"  {n['namespace']}.{n['key']:30s} [{n['type']['name']}]  {n['name']!r}")
