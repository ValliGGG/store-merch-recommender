"""Clear bogus compareAtPrice on promo-collection variants.

Definition of "bogus" used here:
  A product where NO variant has compareAtPrice > price (i.e. nothing actually on sale)
  but at least one variant has compareAtPrice > 0. Those variants get compareAtPrice = null.

Effect:
  - Smart collections like `promocje` / `zlava` / `akcije` / `popusti` (rule:
    VARIANT_COMPARE_AT_PRICE > 0.01) auto-remove the product within a few minutes.
  - Storefront stops showing false discount badges / strikethroughs.

A backup of all original compareAtPrice values is written to backups/<store>_compareAt_backup_<ts>.json
so the change is reversible.

Usage:
    python _clear_fake_compare_at.py --dry-run            # all stores, no writes
    python _clear_fake_compare_at.py                      # all stores, apply
    python _clear_fake_compare_at.py --store BA           # single store
"""
from __future__ import annotations
import argparse, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig

cfg = cfg_mod.load()

PROMO = {"SK": "zlava", "PL": "promocje", "BA": "akcije", "MK": "popusti"}

FIND_Q = "query ($h:String!){ collectionByHandle(handle:$h){ id handle productsCount{count} } }"

VARIANTS_Q = """
query ($id: ID!, $cursor: String) {
  collection(id: $id) {
    products(first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node {
        id handle title totalVariants
        variants(first: 250) { pageInfo { hasNextPage endCursor }
          edges { node { id sku price compareAtPrice } } }
      } }
    }
  }
}
"""

# Used only for products with > 250 variants — paginate the rest.
PRODUCT_VARIANTS_Q = """
query ($id: ID!, $cursor: String) {
  product(id: $id) {
    variants(first: 250, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node { id sku price compareAtPrice } }
    }
  }
}
"""

# Bulk-update variants for a product. compareAtPrice: null clears it.
UPDATE_M = """
mutation ($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    userErrors { field message }
  }
}
"""


def _variant_tuple(v):
    try:
        p  = float(v.get("price") or 0)
        ca = float(v.get("compareAtPrice") or 0)
    except (TypeError, ValueError):
        return None
    return (v["id"], v.get("sku") or "", p, ca, v.get("compareAtPrice"))


def _paginate_remaining_variants(client, product_gid, after_cursor):
    """Continue variant pagination for a product beyond the first page returned by the collection query."""
    extra = []
    cursor = after_cursor
    while True:
        d = client.execute(PRODUCT_VARIANTS_Q, {"id": product_gid, "cursor": cursor})
        page = d["product"]["variants"]
        for e in page["edges"]:
            t = _variant_tuple(e["node"])
            if t: extra.append(t)
        pi = page["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]
    return extra


def fetch_promo_products(client, coll_id):
    """Returns [(product_id, handle, title, [(variant_id, sku, price, compareAt, raw), ...])]
    Variants are FULLY paginated (handles products with >250 variants)."""
    out = []
    cursor = None
    while True:
        d = client.execute(VARIANTS_Q, {"id": coll_id, "cursor": cursor})
        c = d["collection"]
        for e in c["products"]["edges"]:
            n = e["node"]
            variants = []
            for ve in n["variants"]["edges"]:
                t = _variant_tuple(ve["node"])
                if t: variants.append(t)
            # If product has more variants beyond the first 250, paginate
            v_pi = n["variants"]["pageInfo"]
            if v_pi["hasNextPage"]:
                variants.extend(_paginate_remaining_variants(client, n["id"], v_pi["endCursor"]))
            out.append((n["id"], n["handle"], n["title"], variants))
        pi = c["products"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]
    return out


def classify(variants):
    """Return (is_fully_fake, fake_variant_ids).

    Fully fake = no variant where compareAt > price. Fake variants = those where
    compareAt > 0 and compareAt <= price (meaningless compareAt).
    """
    any_real_sale = any(ca > p for (_id, _sku, p, ca, _raw) in variants)
    if any_real_sale:
        return False, []
    fake_ids = [vid for (vid, _sku, p, ca, _raw) in variants if 0 < ca <= p]
    return True, fake_ids


def process_store(code: str, dry_run: bool):
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    tok = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    if not url:
        print(f"[{code}] no env, skip"); return
    shop = ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version)
    client = ShopifyClient(shop)

    d = client.execute(FIND_Q, {"h": PROMO[code]})
    coll = d.get("collectionByHandle")
    if not coll:
        print(f"[{code}] no promo {PROMO[code]}"); return

    print(f"\n[{code}] {coll['handle']}  total={coll['productsCount']['count']}  "
          f"mode={'DRY-RUN' if dry_run else 'APPLY'}")

    products = fetch_promo_products(client, coll["id"])
    fake_products = []
    backup_rows = []
    for pid, handle, title, variants in products:
        is_fake, fake_ids = classify(variants)
        if not is_fake or not fake_ids:
            continue
        fake_products.append((pid, handle, title, fake_ids))
        # Backup raw compareAt values for these variants
        for (vid, sku, p, ca, raw) in variants:
            if vid in fake_ids:
                backup_rows.append({
                    "product_id": pid, "handle": handle,
                    "variant_id": vid, "sku": sku,
                    "price": p, "compareAtPrice": raw,
                })

    print(f"   products to clean: {len(fake_products)}   variants to clear: {len(backup_rows)}")
    if not fake_products:
        return

    # Backup
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    Path("backups").mkdir(exist_ok=True)
    bpath = Path(f"backups/{code}_compareAt_backup_{ts}.json")
    bpath.write_text(json.dumps({
        "store": code, "collection": coll["handle"],
        "ts_utc": ts, "rows": backup_rows,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"   backup: {bpath}  ({len(backup_rows)} variants)")

    if dry_run:
        # Show first 5 examples
        for pid, h, t, fake_ids in fake_products[:5]:
            print(f"     dry-run: {h[:50]:50s}  would clear {len(fake_ids)} variants")
        return

    # Apply mutations
    ok = 0; err = 0
    t0 = time.time()
    for i, (pid, handle, title, fake_ids) in enumerate(fake_products, 1):
        var_payload = [{"id": vid, "compareAtPrice": None} for vid in fake_ids]
        try:
            d = client.execute(UPDATE_M, {"productId": pid, "variants": var_payload})
            errs = d["productVariantsBulkUpdate"]["userErrors"]
            if errs:
                err += 1
                print(f"   ! [{handle[:40]}] {errs}")
            else:
                ok += 1
        except Exception as e:
            err += 1
            print(f"   ! [{handle[:40]}] EXC {e}")
        if i % 100 == 0:
            elapsed = time.time() - t0
            print(f"   ... {i}/{len(fake_products)}  ok={ok} err={err}  {elapsed:.0f}s")

    elapsed = time.time() - t0
    print(f"   DONE  ok={ok}  err={err}  total={len(fake_products)}  in {elapsed:.0f}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", choices=["SK","PL","BA","MK"], default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    stores = [args.store] if args.store else ["SK", "PL", "BA", "MK"]
    for s in stores:
        process_store(s, args.dry_run)


if __name__ == "__main__":
    main()
