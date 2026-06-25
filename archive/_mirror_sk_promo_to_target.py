"""Mirror SK promotional discounts to a target store (PL / BA / MK).

For each on-sale SK variant, find the matching target variant by SKU.
- If target variant already on sale (compareAt > price): skip (respect local merchant pricing).
- Otherwise: compute target_new_price = round_down(target_price * (1 - SK_disc/100), grain[T])
            Set price = target_new_price, compareAtPrice = target_full_price.
- Always rounds DOWN so effective discount >= advertised SK discount.

Usage:
    python _mirror_sk_promo_to_target.py --target BA --dry-run
    python _mirror_sk_promo_to_target.py --target BA
    python _mirror_sk_promo_to_target.py --target PL
    python _mirror_sk_promo_to_target.py --target MK

Cache:
    First call (regardless of target) builds backups/sk_on_sale_cache.json.
    Subsequent calls reuse it for ~30s startup vs ~3min fresh fetch.
"""
from __future__ import annotations
import argparse, csv, json, os, sys, time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig
cfg = cfg_mod.load()

# Rounding grain per target store currency
GRAIN = {
    "SK": Decimal("0.10"),  # EUR — .X0 endings dominant
    "PL": Decimal("0.10"),  # PLN — .X0 (with .90 most common)
    "BA": Decimal("0.10"),  # BAM — mix of .X0 and .X9
    "MK": Decimal("1.00"),  # MKD — integer (98% prices end in .00)
}

# ---------- SK side ----------
SK_PROMO_HANDLE = "zlava"

FIND_Q = "query ($h:String!){ collectionByHandle(handle:$h){ id handle productsCount{count} } }"

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

TARGET_VARIANT_LOOKUP_Q = """
query ($q: String!) {
  productVariants(first: 5, query: $q) {
    edges { node {
      id sku price compareAtPrice
      product { id handle title }
    } }
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


def fetch_sk_on_sale(force: bool = False) -> list[dict]:
    """Returns list of {sku, sk_handle, sk_title, sk_price, sk_compareAt, sk_discount_pct}.
    Caches to backups/sk_on_sale_cache.json (1-hour TTL)."""
    cache = Path("backups/sk_on_sale_cache.json")
    if not force and cache.exists() and (time.time() - cache.stat().st_mtime) < 3600:
        print(f"   reusing SK cache ({cache})")
        return json.loads(cache.read_text(encoding="utf-8"))

    print("   fetching fresh SK on-sale data...")
    client = get_client("SK")
    coll = client.execute(FIND_Q, {"h": SK_PROMO_HANDLE})["collectionByHandle"]
    out = []
    cursor = None
    while True:
        d = client.execute(SK_VARIANTS_Q, {"id": coll["id"], "cursor": cursor})
        c = d["collection"]
        for e in c["products"]["edges"]:
            n = e["node"]
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
                    p = float(v.get("price") or 0); ca = float(v.get("compareAtPrice") or 0)
                except: continue
                if ca > p:
                    pct = round((ca - p) / ca * 100, 2)
                    out.append({
                        "sku": sku, "sk_handle": n["handle"], "sk_title": n["title"],
                        "sk_price": p, "sk_compareAt": ca, "sk_discount_pct": pct,
                    })
        pi = c["products"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"   cached {len(out)} on-sale variants -> {cache}")
    return out


def round_down_price(raw: float, grain: Decimal) -> Decimal:
    """Round `raw` DOWN to nearest `grain`. Always returns a Decimal."""
    if raw <= 0: return Decimal("0")
    raw_d = Decimal(str(round(raw, 6)))
    return (raw_d / grain).quantize(Decimal("1"), rounding=ROUND_DOWN) * grain


def lookup_target_variant(client: ShopifyClient, sku: str):
    d = client.execute(TARGET_VARIANT_LOOKUP_Q, {"q": f"sku:{sku}"})
    edges = d["productVariants"]["edges"]
    return edges[0]["node"] if edges else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, choices=["PL", "BA", "MK"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-refresh-sk", action="store_true",
                    help="ignore SK cache and re-fetch")
    args = ap.parse_args()

    code = args.target
    grain = GRAIN[code]
    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(f"\n=== Mirror SK -> {code}  grain={grain}  mode={mode} ===")

    # 1. SK on-sale data
    sk_sales = fetch_sk_on_sale(force=args.force_refresh_sk)
    print(f"   SK on-sale variants: {len(sk_sales)}")

    # 2. Target lookup + classify
    print(f"\n[1/2] Looking up target variants and computing changes...")
    tclient = get_client(code)
    plan_rows = []         # variants to mutate
    skip_already_sale = 0
    skip_not_in_target = 0
    skip_disc_too_small = 0
    skip_invalid = 0

    for i, s in enumerate(sk_sales, 1):
        if i % 200 == 0:
            print(f"   {i}/{len(sk_sales)}  to_mutate={len(plan_rows)}  "
                  f"already_sale={skip_already_sale}  not_in_target={skip_not_in_target}")
        try:
            tv = lookup_target_variant(tclient, s["sku"])
        except Exception as e:
            skip_invalid += 1; continue
        if not tv:
            skip_not_in_target += 1; continue
        try:
            t_price = float(tv.get("price") or 0)
            t_ca    = float(tv.get("compareAtPrice") or 0)
        except: skip_invalid += 1; continue
        if t_price <= 0: skip_invalid += 1; continue
        if t_ca > t_price:
            skip_already_sale += 1; continue   # already locally on sale, respect

        disc = s["sk_discount_pct"]
        raw_new = t_price * (1 - disc / 100.0)
        new_price = round_down_price(raw_new, grain)
        if new_price <= 0:
            skip_disc_too_small += 1; continue

        new_compareAt = Decimal(str(t_price))   # the original full price
        if new_price >= new_compareAt:
            # rounding ate the discount entirely (very small price + small disc)
            skip_disc_too_small += 1; continue

        eff_disc = float((new_compareAt - new_price) / new_compareAt * 100)
        plan_rows.append({
            "sku": s["sku"],
            "sk_disc_pct": disc,
            "target_variant_id": tv["id"],
            "target_product_id": tv["product"]["id"],
            "target_handle": tv["product"]["handle"],
            "target_title": tv["product"]["title"][:60],
            "old_price": t_price,
            "old_compareAt": t_ca,
            "new_price": float(new_price),
            "new_compareAt": float(new_compareAt),
            "effective_disc_pct": round(eff_disc, 2),
        })

    print(f"\n[2/2] Plan summary for {code}:")
    print(f"   to mutate:                {len(plan_rows)}")
    print(f"   skipped (already on sale): {skip_already_sale}")
    print(f"   skipped (not in target):   {skip_not_in_target}")
    print(f"   skipped (disc too small):  {skip_disc_too_small}")
    print(f"   skipped (invalid):         {skip_invalid}")

    # Save preview CSV always
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    Path("backups").mkdir(exist_ok=True)
    preview = Path(f"backups/{code}_promo_mirror_preview_{ts}.csv")
    if plan_rows:
        with open(preview, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(plan_rows[0].keys()))
            w.writeheader(); w.writerows(plan_rows)
        print(f"   preview CSV: {preview}  ({len(plan_rows)} rows)")

    # Backup snapshot of current target state for any variant we plan to touch
    backup = Path(f"backups/{code}_promo_apply_backup_{ts}.json")
    backup.write_text(json.dumps([
        {"variant_id": r["target_variant_id"], "old_price": r["old_price"], "old_compareAt": r["old_compareAt"]}
        for r in plan_rows
    ], indent=2), encoding="utf-8")
    print(f"   backup:      {backup}")

    if args.dry_run:
        # Show first 8 examples
        print(f"\n   First 8 planned changes:")
        for r in plan_rows[:8]:
            print(f"     [{r['sk_disc_pct']:>5.1f}% SK -> {r['effective_disc_pct']:>5.1f}% T]  "
                  f"{r['old_price']:>7.2f} -> {r['new_price']:>7.2f} "
                  f"(compareAt {r['new_compareAt']:>7.2f})  {r['target_handle'][:48]}")
        print("\n   DRY-RUN mode — no mutations applied.")
        return

    # APPLY
    if not plan_rows:
        print("   nothing to apply"); return

    # Group by product (one mutation per product, multiple variants).
    # Dedupe by target_variant_id within each product — two SK on-sale variants
    # can share the same SKU and resolve to the same target variant.
    by_product: dict[str, list[dict]] = {}
    seen_variants_per_product: dict[str, set[str]] = {}
    for r in plan_rows:
        seen = seen_variants_per_product.setdefault(r["target_product_id"], set())
        if r["target_variant_id"] in seen:
            continue
        seen.add(r["target_variant_id"])
        by_product.setdefault(r["target_product_id"], []).append(r)
    print(f"\n[apply] {len(plan_rows)} variants across {len(by_product)} products")
    ok = 0; err = 0; t0 = time.time()
    for i, (pid, rows) in enumerate(by_product.items(), 1):
        payload = [{"id": r["target_variant_id"],
                    "price": f"{r['new_price']:.2f}",
                    "compareAtPrice": f"{r['new_compareAt']:.2f}"} for r in rows]
        try:
            d = tclient.execute(UPDATE_M, {"productId": pid, "variants": payload})
            errs = d["productVariantsBulkUpdate"]["userErrors"]
            if errs:
                err += 1
                print(f"   ! [{rows[0]['target_handle'][:40]}] {errs}")
            else:
                ok += 1
        except Exception as e:
            err += 1
            print(f"   ! [{rows[0]['target_handle'][:40]}] EXC {e}")
        if i % 100 == 0:
            print(f"   ... {i}/{len(by_product)}  ok={ok} err={err}  {time.time()-t0:.0f}s")

    print(f"\n   DONE  ok={ok}  err={err}  total_products={len(by_product)}  "
          f"total_variants={len(plan_rows)}  in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
