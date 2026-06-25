"""Compare SK vs BA promotions.

Goal: identify products on sale in SK (zlava) that have a BA counterpart NOT on sale.
Match SK <-> BA at variant SKU level (most reliable cross-store join).

Output: counts + a sample list + a CSV for the user to review.
"""
import os, sys, csv
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig
cfg = cfg_mod.load()

PROMO = {"SK":"zlava", "BA":"akcije"}

FIND_Q = "query ($h:String!){ collectionByHandle(handle:$h){ id handle productsCount{count} } }"

# SK side: walk promo collection, for each on-sale variant collect (sku, discount_pct, product_handle)
SK_VARIANTS_Q = """
query ($id: ID!, $cursor: String) {
  collection(id: $id) {
    products(first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node { id handle title totalVariants
        variants(first: 250) { pageInfo{ hasNextPage endCursor }
          edges { node { id sku price compareAtPrice } } } } }
    }
  }
}
"""
SK_PRODUCT_VARIANTS_Q = """
query ($id: ID!, $cursor: String) {
  product(id: $id) {
    variants(first: 250, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node { id sku price compareAtPrice } } } }
}
"""

# BA side: lookup variant by SKU
BA_VARIANT_LOOKUP_Q = """
query ($q: String!) {
  productVariants(first: 5, query: $q) {
    edges { node {
      id sku price compareAtPrice
      product { id handle title }
    } }
  }
}
"""

def get_client(code):
    url = os.environ[f"ARTMIE_{code}_STORE_URL"]
    tok = os.environ[f"ARTMIE_{code}_API_TOKEN"]
    return ShopifyClient(ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version))

def fetch_sk_on_sale_variants():
    """Returns list of dicts: {sku, sk_handle, sk_title, sk_price, sk_compareAt, sk_discount_pct}"""
    client = get_client("SK")
    coll = client.execute(FIND_Q, {"h": PROMO["SK"]})["collectionByHandle"]
    print(f"SK promo: {coll['handle']} count={coll['productsCount']['count']}")

    out = []
    cursor = None
    n_products = 0
    while True:
        d = client.execute(SK_VARIANTS_Q, {"id": coll["id"], "cursor": cursor})
        c = d["collection"]
        for e in c["products"]["edges"]:
            n = e["node"]; n_products += 1
            # gather variants (paginate if >250)
            vs = list(n["variants"]["edges"])
            v_pi = n["variants"]["pageInfo"]
            cur_v = v_pi["endCursor"] if v_pi["hasNextPage"] else None
            while cur_v:
                d2 = client.execute(SK_PRODUCT_VARIANTS_Q, {"id": n["id"], "cursor": cur_v})
                vs.extend(d2["product"]["variants"]["edges"])
                pi2 = d2["product"]["variants"]["pageInfo"]
                cur_v = pi2["endCursor"] if pi2["hasNextPage"] else None
            for ve in vs:
                v = ve["node"]
                sku = (v.get("sku") or "").strip()
                if not sku: continue
                try:
                    p  = float(v.get("price") or 0)
                    ca = float(v.get("compareAtPrice") or 0)
                except: continue
                if ca > p:  # truly on sale
                    pct = round((ca - p) / ca * 100, 1) if ca else 0
                    out.append({
                        "sku": sku, "sk_handle": n["handle"], "sk_title": n["title"],
                        "sk_price": p, "sk_compareAt": ca, "sk_discount_pct": pct,
                    })
        pi = c["products"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]
    print(f"   walked {n_products} products, {len(out)} on-sale variants")
    return out

def lookup_ba_variant(client, sku):
    """Find a BA variant matching this SKU. Returns first match or None."""
    d = client.execute(BA_VARIANT_LOOKUP_Q, {"q": f"sku:{sku}"})
    edges = d["productVariants"]["edges"]
    return edges[0]["node"] if edges else None

def main():
    print("[1/3] Fetching SK on-sale variants...")
    sk_sales = fetch_sk_on_sale_variants()
    if not sk_sales:
        print("No SK sales — exit"); return

    print(f"\n[2/3] Looking up matching BA variants by SKU ({len(sk_sales)} lookups)...")
    ba_client = get_client("BA")
    matched = 0; ba_on_sale = 0; ba_no_sale = 0; not_in_ba = 0
    rows = []
    for i, s in enumerate(sk_sales, 1):
        if i % 100 == 0: print(f"   {i}/{len(sk_sales)}  matched={matched}  ba_no_sale={ba_no_sale}")
        try:
            bv = lookup_ba_variant(ba_client, s["sku"])
        except Exception as e:
            print(f"   ! lookup failed for {s['sku']}: {e}"); continue
        if not bv:
            not_in_ba += 1
            continue
        matched += 1
        try:
            bp = float(bv.get("price") or 0)
            bca = float(bv.get("compareAtPrice") or 0)
        except: bp, bca = 0, 0
        on_sale_in_ba = bca > bp
        if on_sale_in_ba:
            ba_on_sale += 1
        else:
            ba_no_sale += 1
            rows.append({
                "sku": s["sku"],
                "sk_handle": s["sk_handle"],
                "sk_title": s["sk_title"][:60],
                "sk_price": s["sk_price"],
                "sk_compareAt": s["sk_compareAt"],
                "sk_discount_pct": s["sk_discount_pct"],
                "ba_handle": bv["product"]["handle"],
                "ba_title": bv["product"]["title"][:60],
                "ba_price": bp,
                "ba_compareAt": bca,
            })

    print(f"\n[3/3] Results:")
    print(f"   SK on-sale variants:                 {len(sk_sales)}")
    print(f"   matched in BA by SKU:                {matched}  ({100*matched//max(len(sk_sales),1)}%)")
    print(f"     of which already on sale in BA:    {ba_on_sale}")
    print(f"     of which NOT on sale in BA (gap):  {ba_no_sale}  <-- problem")
    print(f"   not present in BA at all:            {not_in_ba}")

    # Aggregate gap by SK product (multiple variants per product)
    by_product = defaultdict(list)
    for r in rows:
        by_product[r["sk_handle"]].append(r)
    print(f"\n   distinct SK products with BA gap:    {len(by_product)}")

    # Save CSV
    out_path = Path("backups") / "sk_ba_promo_gap.csv"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print(f"\n   gap CSV: {out_path}  ({len(rows)} variant rows, {len(by_product)} SK products)")

    # Show first 10 sample products
    print(f"\n   First 10 SK products on sale but NOT on sale in BA:")
    for sk_h, items in list(by_product.items())[:10]:
        first = items[0]
        print(f"     {first['sk_discount_pct']:>5.1f}%  {sk_h[:55]:55s}  -> BA: {first['ba_handle'][:55]}")

if __name__ == "__main__":
    main()
