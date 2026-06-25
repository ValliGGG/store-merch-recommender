"""Inverse of _mirror_sk_promo_to_target.py.

For each variant currently on sale in a target store (PL/BA/MK), look up the
matching SK variant by SKU. If the SK variant is NOT on sale (or doesn't exist),
remove the sale from the target by:
    new_price        = current compareAtPrice  (the original full price)
    new_compareAtPrice = null                 (clear the strikethrough)

This treats SK as the source of truth: target stores should have the SAME SET
of on-sale SKUs as SK — no more, no less.

Backup written to backups/{STORE}_unmirror_backup_<ts>.json so the change is
fully reversible.

Usage:
    python _unmirror_extra_sales.py --target BA --dry-run
    python _unmirror_extra_sales.py --target BA
"""
from __future__ import annotations
import argparse, csv, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig
cfg = cfg_mod.load()

PROMO_HANDLE = {"PL": "promocje", "BA": "akcije", "MK": "popusti"}

FIND_Q = "query ($h:String!){ collectionByHandle(handle:$h){ id handle productsCount{count} } }"

# Walk target promo collection, get all on-sale variants
TARGET_VARIANTS_Q = """
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
PRODUCT_VARIANTS_Q = """
query ($id: ID!, $cursor: String) {
  product(id: $id) {
    variants(first: 250, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node { id sku price compareAtPrice } } } }
}
"""

# SK lookup by SKU - is this SKU on sale in SK?
SK_LOOKUP_Q = """
query ($q: String!) {
  productVariants(first: 5, query: $q) {
    edges { node { id sku price compareAtPrice product { handle } } }
  }
}
"""

UPDATE_M = """
mutation ($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    userErrors { field message }
  }
}
"""


def get_client(code: str) -> ShopifyClient:
    url = os.environ[f"ARTMIE_{code}_STORE_URL"]
    tok = os.environ[f"ARTMIE_{code}_API_TOKEN"]
    return ShopifyClient(ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version))


def load_sk_on_sale_skus() -> set:
    """Return set of SKUs currently on sale in SK (from cache or fresh fetch)."""
    cache = Path("backups/sk_on_sale_cache.json")
    if cache.exists() and (time.time() - cache.stat().st_mtime) < 3600:
        data = json.loads(cache.read_text(encoding="utf-8"))
        return {row["sku"] for row in data}
    # else import from mirror script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _mirror_sk_promo_to_target import fetch_sk_on_sale
    data = fetch_sk_on_sale(force=False)
    return {row["sku"] for row in data}


def fetch_target_on_sale(client: ShopifyClient, coll_id: str) -> list[dict]:
    """Walk target promo collection, return all variants where compareAt > price."""
    out = []
    cursor = None
    while True:
        d = client.execute(TARGET_VARIANTS_Q, {"id": coll_id, "cursor": cursor})
        c = d["collection"]
        for e in c["products"]["edges"]:
            n = e["node"]
            vs = list(n["variants"]["edges"])
            v_pi = n["variants"]["pageInfo"]
            cur_v = v_pi["endCursor"] if v_pi["hasNextPage"] else None
            while cur_v:
                d2 = client.execute(PRODUCT_VARIANTS_Q, {"id": n["id"], "cursor": cur_v})
                vs.extend(d2["product"]["variants"]["edges"])
                pi2 = d2["product"]["variants"]["pageInfo"]
                cur_v = pi2["endCursor"] if pi2["hasNextPage"] else None
            for ve in vs:
                v = ve["node"]
                sku = (v.get("sku") or "").strip()
                if not sku: continue
                try:
                    p = float(v.get("price") or 0); ca = float(v.get("compareAtPrice") or 0)
                except: continue
                if ca > p:
                    out.append({
                        "sku": sku,
                        "product_id": n["id"], "handle": n["handle"], "title": n["title"],
                        "variant_id": v["id"], "price": p, "compareAtPrice": ca,
                    })
        pi = c["products"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, choices=["PL", "BA", "MK"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    code = args.target
    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(f"\n=== Un-mirror SK <- {code}  mode={mode} ===")

    print("[1/3] Loading SK on-sale SKU set...")
    sk_skus = load_sk_on_sale_skus()
    print(f"   SK currently has {len(sk_skus)} on-sale SKUs")

    print(f"\n[2/3] Walking {code} promo collection...")
    tclient = get_client(code)
    coll = tclient.execute(FIND_Q, {"h": PROMO_HANDLE[code]})["collectionByHandle"]
    print(f"   {coll['handle']}  productsCount(cached)={coll['productsCount']['count']}")
    t_sales = fetch_target_on_sale(tclient, coll["id"])
    print(f"   {code} actually has {len(t_sales)} on-sale variants")

    extras = [t for t in t_sales if t["sku"] not in sk_skus]
    aligned = [t for t in t_sales if t["sku"] in sk_skus]
    print(f"   aligned with SK:        {len(aligned)}")
    print(f"   EXTRA (to remove sale): {len(extras)}")

    if not extras:
        print("   nothing to do — already aligned"); return

    # Save preview & backup
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    Path("backups").mkdir(exist_ok=True)
    preview = Path(f"backups/{code}_unmirror_preview_{ts}.csv")
    with open(preview, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(extras[0].keys()))
        w.writeheader(); w.writerows(extras)
    print(f"   preview CSV: {preview}")

    backup = Path(f"backups/{code}_unmirror_backup_{ts}.json")
    backup.write_text(json.dumps(extras, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"   backup:      {backup}")

    if args.dry_run:
        print("\n   First 8 extras (would remove sale):")
        for x in extras[:8]:
            print(f"     {x['handle'][:48]:48s} price={x['price']:>7.2f} ca={x['compareAtPrice']:>7.2f}  sku={x['sku']}")
        return

    # Apply: dedupe by variant id per product
    by_product: dict[str, list[dict]] = {}
    seen: dict[str, set[str]] = {}
    for x in extras:
        s = seen.setdefault(x["product_id"], set())
        if x["variant_id"] in s: continue
        s.add(x["variant_id"])
        by_product.setdefault(x["product_id"], []).append(x)
    print(f"\n[3/3] Applying — {len(extras)} variants across {len(by_product)} products")
    ok = 0; err = 0; t0 = time.time()
    for i, (pid, rows) in enumerate(by_product.items(), 1):
        # New price = current compareAtPrice (the original full price), compareAt = null
        payload = [{"id": r["variant_id"],
                    "price": f"{r['compareAtPrice']:.2f}",
                    "compareAtPrice": None} for r in rows]
        try:
            d = tclient.execute(UPDATE_M, {"productId": pid, "variants": payload})
            errs = d["productVariantsBulkUpdate"]["userErrors"]
            if errs:
                err += 1
                print(f"   ! [{rows[0]['handle'][:40]}] {errs}")
            else:
                ok += 1
        except Exception as e:
            err += 1
            print(f"   ! [{rows[0]['handle'][:40]}] EXC {e}")
        if i % 100 == 0:
            print(f"   ... {i}/{len(by_product)}  ok={ok} err={err}  {time.time()-t0:.0f}s")

    print(f"\n   DONE  ok={ok}  err={err}  total_products={len(by_product)}  in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
