"""Initial 24-month order backfill via Shopify bulk operation.

- Computes the date threshold from config.backfill.months
- Aborts if a bulk op is already running on the shop
- Polls until the bulk op completes
- Streams the JSONL result, dropping line items pointing to deleted products
- Inserts orders + line_items into SQLite (idempotent: INSERT OR REPLACE)

Bulk op JSONL records are flat — orders appear at top level, line items
have a __parentId pointing at their parent order id.

Usage:
    python scripts/01_initial_export.py
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import bulk_ops, config as cfg_mod, db as db_mod
from lib.shopify_client import ShopifyClient


def threshold_date(months: int) -> str:
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=months * 30)  # approximate: ~30 d/mo is enough
    return cutoff.isoformat()


def build_bulk_query(since_iso_date: str) -> str:
    return f'''
    {{
      orders(query: "status:any AND test:false AND created_at:>={since_iso_date}") {{
        edges {{
          node {{
            id
            createdAt
            cancelledAt
            displayFinancialStatus
            customer {{ id }}
            lineItems {{
              edges {{
                node {{
                  id
                  quantity
                  product {{ id legacyResourceId }}
                  variant {{ id }}
                  originalUnitPriceSet {{ shopMoney {{ amount currencyCode }} }}
                  refundableQuantity
                }}
              }}
            }}
          }}
        }}
      }}
    }}
    '''


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

    since = threshold_date(cfg.backfill_months)
    print(f"backfill window: {cfg.backfill_months} months -> orders since {since}")

    # Check no other bulk op running
    op = bulk_ops.current(client)
    if op and op["status"] in ("CREATED", "RUNNING"):
        print(f"ERROR: bulk op already in progress: {op['id']} status={op['status']}", file=sys.stderr)
        sys.exit(2)

    with db_mod.run(conn, "initial", notes=f"backfill since {since}"):
        query = build_bulk_query(since)
        op_id = bulk_ops.start(client, query)
        print(f"started bulk op {op_id}")
        result = bulk_ops.wait_for_completion(client, op_id, poll_seconds=20)
        print(f"completed: objects={result['objectCount']} bytes={result['fileSize']}")

        if not result.get("url"):
            print("WARNING: bulk op completed but no URL (zero rows?). Aborting.", file=sys.stderr)
            return

        jsonl_path = cfg.db_path.parent / f"_bulk_orders_{op_id.split('/')[-1]}.jsonl"
        bulk_ops.download_jsonl(result["url"], jsonl_path)

        # Build set of known product GIDs to drop dead-row line items
        known_pids = {row[0] for row in conn.execute("SELECT id FROM products")}
        if not known_pids:
            print("WARNING: products table empty — run 02b_refresh_products.py first.", file=sys.stderr)

        # Pass 1: insert orders
        # Pass 2: insert line items (need order to exist for FK)
        orders_seen = 0
        items_seen = 0
        items_dropped = 0
        t0 = time.time()
        for record in bulk_ops.iter_jsonl(jsonl_path):
            if "__parentId" not in record:
                # Order record
                conn.execute(
                    """INSERT OR REPLACE INTO orders(
                          id, created_at, customer_id, cancelled_at, financial_status
                       ) VALUES (?,?,?,?,?)""",
                    (
                        record["id"],
                        record.get("createdAt"),
                        (record.get("customer") or {}).get("id"),
                        record.get("cancelledAt"),
                        record.get("displayFinancialStatus"),
                    ),
                )
                orders_seen += 1
            else:
                # Line item
                prod = record.get("product") or {}
                pid = prod.get("id")
                if not pid or (known_pids and pid not in known_pids):
                    items_dropped += 1
                    continue
                price_node = ((record.get("originalUnitPriceSet") or {}).get("shopMoney") or {})
                qty = int(record.get("quantity") or 0)
                # refundableQuantity = units still refundable; refunded ≈ qty - that.
                # Lets scoring count KEPT units (quantity - refunded_quantity).
                refundable = record.get("refundableQuantity")
                refunded = max(qty - int(refundable), 0) if refundable is not None else 0
                conn.execute(
                    """INSERT OR REPLACE INTO line_items(
                          id, order_id, product_id, product_legacy_id, variant_id,
                          quantity, refunded_quantity, unit_price, currency
                       ) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        record["id"],
                        record["__parentId"],
                        pid,
                        int(prod["legacyResourceId"]) if prod.get("legacyResourceId") else None,
                        (record.get("variant") or {}).get("id"),
                        qty,
                        refunded,
                        float(price_node["amount"]) if price_node.get("amount") else None,
                        price_node.get("currencyCode"),
                    ),
                )
                items_seen += 1
                if items_seen % 10000 == 0:
                    conn.commit()
                    print(f"  inserted {items_seen} line items, {orders_seen} orders so far...")

        conn.commit()
        elapsed = time.time() - t0
        print(f"\nDONE in {elapsed:.1f}s — {orders_seen} orders, {items_seen} line items "
              f"({items_dropped} dropped pointing at deleted products)")


if __name__ == "__main__":
    main()
