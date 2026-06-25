"""Refresh the local product cache with brand + occasion + status.

Pulls every product (paginated 100/page) with the metafields we care about,
resolves brand via config selectors, maps occasions to season tags, and
upserts into SQLite.

Verification: prints the count of products resolved as Artmie.  If the count
is 0, it raises — silent zero-match would be a silent failure (per spec §10).

Usage:
    python scripts/02b_refresh_products.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg_mod, db as db_mod, seasonal, season_keywords
from lib.brand_resolver import resolve as resolve_brand
from lib.shopify_client import ShopifyClient

# Eligibility filter (per-store, from config.handle_filter).
# The SK store hosts foreign-market clone products (e.g. -de- handles) via
# Shopify Markets, so SK sets handle_filter "-sk-" to keep only SK products.
# Expansion stores are single-country and standalone, so they set no filter
# (handle_filter: null) and the whole catalog is eligible.  Verified live
# 2026-06-25 that "-sk-" matches 0% of handles on every expansion store, so a
# hardcoded "-sk-" here would silently empty the cache off-SK.
import re

# first:50 (not 100) — the variants sub-connection raises per-query cost.
QUERY = """
query Products($cursor: String) {
  products(first: 50, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        legacyResourceId
        handle
        title
        vendor
        productType
        tags
        status
        totalInventory
        createdAt
        updatedAt
        priceRangeV2 {
          minVariantPrice { amount currencyCode }
        }
        compareAtPriceRange {
          maxVariantCompareAtPrice { amount currencyCode }
        }
        metafields(first: 30) {
          edges { node { namespace key type value } }
        }
        variants(first: 40) {
          edges { node {
            availableForSale
            deliverySource: metafield(namespace: "delivery", key: "source") { value }
          } }
        }
      }
    }
  }
}
"""


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=None, help="store code (default: sk / $ARTMIE_STORE)")
    args = ap.parse_args()
    cfg = cfg_mod.load(args.store)
    print(f"[{cfg.store}] shop: {cfg.shop.store_url}")
    client = ShopifyClient(cfg.shop)
    conn = db_mod.connect(cfg.db_path)
    db_mod.ensure_schema(conn)

    selectors = cfg.artmie_brand["selectors"]
    season_cfg = cfg.seasonal

    # External (supplier) warehouse detection.
    ext_cfg = cfg.raw.get("external_stock", {}) or {}
    ext_value = ext_cfg.get("source_external_value", "supplier")
    ext_demote = bool(ext_cfg.get("demote", True))

    # Optional per-store eligibility filter on product handle.
    handle_filter = cfg.handle_filter
    handle_re = re.compile(re.escape(handle_filter)) if handle_filter else None
    print(f"  handle filter: {handle_filter!r}" if handle_filter else "  handle filter: (none — whole catalog)")

    with db_mod.run(conn, "products", notes="full product cache refresh"):
        cursor = None
        page = 0
        upserted = 0
        artmie_count = 0
        t0 = time.time()
        while True:
            page += 1
            data = client.execute(QUERY, {"cursor": cursor})
            conn_pi = data["products"]["pageInfo"]
            rows = data["products"]["edges"]
            for e in rows:
                p = e["node"]
                # Per-store eligibility filter (foreign-market products excluded)
                if handle_re and not handle_re.search(p.get("handle") or ""):
                    continue
                mfs = [mf["node"] for mf in p["metafields"]["edges"]]
                brand, is_artmie = resolve_brand(
                    metafields=mfs, tags=p.get("tags") or [], selectors=selectors
                )
                if is_artmie:
                    artmie_count += 1

                # Own vs external (supplier) availability, from variant
                # delivery.source. A product is external-only when EVERY buyable
                # variant is external (no own-stock variant available).
                own_avail = ext_avail = False
                for ve in p.get("variants", {}).get("edges", []):
                    v = ve["node"]
                    if not v.get("availableForSale"):
                        continue
                    src = (v.get("deliverySource") or {}).get("value")
                    if src == ext_value:
                        ext_avail = True
                    else:
                        own_avail = True
                own_available = 1 if own_avail else 0
                external_only = 1 if (ext_demote and ext_avail and not own_avail) else 0

                # occasions -> season tags
                occ_raw = ""
                for mf in mfs:
                    if mf["namespace"] == "custom" and mf["key"] == "prilezitost":
                        occ_raw = mf["value"] or ""
                        break
                # Stored as JSON list string for list metafield, parse loosely
                occasions: list[str] = []
                if occ_raw:
                    s = occ_raw.strip()
                    if s.startswith("["):
                        import json as _json
                        try:
                            occasions = [str(x) for x in _json.loads(s)]
                        except Exception:
                            occasions = []
                    else:
                        occasions = [s]
                season_tags = seasonal.occasions_to_seasons(occasions, season_cfg)
                # Fallback: keyword detection from title when no occasion metafield
                if not season_tags:
                    inferred = season_keywords.detect(p.get("title") or "")
                    if inferred:
                        season_tags = inferred

                # Compute sale info
                price_min = None
                compare_max = None
                disc = 0.0
                pr = (p.get("priceRangeV2") or {}).get("minVariantPrice") or {}
                if pr.get("amount") is not None:
                    try: price_min = float(pr["amount"])
                    except (TypeError, ValueError): pass
                cmp_ = (p.get("compareAtPriceRange") or {}).get("maxVariantCompareAtPrice") or {}
                if cmp_.get("amount") is not None:
                    try: compare_max = float(cmp_["amount"])
                    except (TypeError, ValueError): pass
                if price_min and compare_max and compare_max > price_min:
                    disc = (compare_max - price_min) / compare_max

                conn.execute(
                    """
                    INSERT INTO products(
                      id, legacy_id, handle, title, vendor, brand, is_artmie,
                      product_type, tags, status, total_inventory,
                      created_at, updated_at, occasion_tags, season_tags,
                      price_min, compare_at_max, discount_pct,
                      own_available, external_only
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      legacy_id=excluded.legacy_id,
                      handle=excluded.handle,
                      title=excluded.title,
                      vendor=excluded.vendor,
                      brand=excluded.brand,
                      is_artmie=excluded.is_artmie,
                      product_type=excluded.product_type,
                      tags=excluded.tags,
                      status=excluded.status,
                      total_inventory=excluded.total_inventory,
                      created_at=excluded.created_at,
                      updated_at=excluded.updated_at,
                      occasion_tags=excluded.occasion_tags,
                      season_tags=excluded.season_tags,
                      price_min=excluded.price_min,
                      compare_at_max=excluded.compare_at_max,
                      discount_pct=excluded.discount_pct,
                      own_available=excluded.own_available,
                      external_only=excluded.external_only
                    """,
                    (
                        p["id"],
                        int(p["legacyResourceId"]) if p.get("legacyResourceId") else None,
                        p.get("handle"),
                        p.get("title"),
                        p.get("vendor"),
                        brand,
                        1 if is_artmie else 0,
                        p.get("productType"),
                        ",".join(p.get("tags") or []),
                        p.get("status"),
                        p.get("totalInventory"),
                        p.get("createdAt"),
                        p.get("updatedAt"),
                        ",".join(occasions),
                        ",".join(season_tags),
                        price_min,
                        compare_max,
                        disc,
                        own_available,
                        external_only,
                    ),
                )
                upserted += 1

            conn.commit()
            print(f"  page {page:3d}  upserted={upserted:6d}  artmie={artmie_count:5d}  "
                  f"throttle={client.throttle.available:.0f}/{client.throttle.maximum:.0f}")
            if not conn_pi["hasNextPage"]:
                break
            cursor = conn_pi["endCursor"]

        elapsed = time.time() - t0
        print(f"\nDONE in {elapsed:.1f}s — {upserted} products, {artmie_count} resolved as Artmie")

        # MANDATORY verification step (spec §4.2)
        if artmie_count == 0:
            print(
                "\nFATAL: zero products resolved as Artmie.\n"
                "Selectors in config.yaml may not match how brand is stored.\n"
                "Inspect a known Artmie product in admin and update selectors.",
                file=sys.stderr,
            )
            sys.exit(2)

        # Print a sanity sample
        sample = conn.execute(
            "SELECT title, brand FROM products WHERE is_artmie=1 LIMIT 5"
        ).fetchall()
        print("\nSample Artmie-resolved products (first 5):")
        for row in sample:
            print(f"  - {row['title'][:70]}  [brand={row['brand']!r}]")


if __name__ == "__main__":
    main()
