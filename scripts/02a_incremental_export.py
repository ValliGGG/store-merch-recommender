"""Incremental order pull — runs weekly after the initial backfill.

Pulls orders created since the last successful run (from sync_runs), or
the last 14 days if no successful run is recorded.  Also re-pulls refunds
within the last 60 days (refunds can lag).

Usage:
    python scripts/02a_incremental_export.py
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import bulk_ops, config as cfg_mod, db as db_mod
from lib.shopify_client import ShopifyClient


def last_success_iso(conn) -> str:
    row = conn.execute(
        "SELECT MAX(finished_at) FROM sync_runs WHERE status='ok' AND kind IN ('initial','incremental')"
    ).fetchone()
    if row and row[0]:
        # Step back 1 day for safety overlap
        last = datetime.fromisoformat(row[0])
        return (last - timedelta(days=1)).date().isoformat()
    return (datetime.now(timezone.utc).date() - timedelta(days=14)).isoformat()


def build_query(since_date: str) -> str:
    return f'''
    {{
      orders(query: "status:any AND test:false AND created_at:>={since_date}") {{
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

    since = last_success_iso(conn)
    print(f"incremental since: {since}")

    op = bulk_ops.current(client)
    if op and op["status"] in ("CREATED", "RUNNING"):
        print(f"ERROR: bulk op already running: {op['id']}", file=sys.stderr)
        sys.exit(2)

    with db_mod.run(conn, "incremental", notes=f"since {since}"):
        op_id = bulk_ops.start(client, build_query(since))
        result = bulk_ops.wait_for_completion(client, op_id, poll_seconds=15)
        if not result.get("url"):
            print("no rows since last run — nothing to ingest")
            return
        path = cfg.db_path.parent / f"_bulk_inc_{op_id.split('/')[-1]}.jsonl"
        bulk_ops.download_jsonl(result["url"], path)

        known = {r[0] for r in conn.execute("SELECT id FROM products")}
        n_orders = n_items = n_drop = 0
        for rec in bulk_ops.iter_jsonl(path):
            if "__parentId" not in rec:
                conn.execute(
                    "INSERT OR REPLACE INTO orders(id, created_at, customer_id, cancelled_at, financial_status) VALUES (?,?,?,?,?)",
                    (rec["id"], rec.get("createdAt"), (rec.get("customer") or {}).get("id"),
                     rec.get("cancelledAt"), rec.get("displayFinancialStatus")),
                )
                n_orders += 1
            else:
                prod = rec.get("product") or {}
                pid = prod.get("id")
                if not pid or (known and pid not in known):
                    n_drop += 1
                    continue
                pn = ((rec.get("originalUnitPriceSet") or {}).get("shopMoney") or {})
                qty = int(rec.get("quantity") or 0)
                refundable = rec.get("refundableQuantity")
                refunded = max(qty - int(refundable), 0) if refundable is not None else 0
                conn.execute(
                    "INSERT OR REPLACE INTO line_items(id, order_id, product_id, product_legacy_id, variant_id, quantity, refunded_quantity, unit_price, currency) VALUES (?,?,?,?,?,?,?,?,?)",
                    (rec["id"], rec["__parentId"], pid,
                     int(prod["legacyResourceId"]) if prod.get("legacyResourceId") else None,
                     (rec.get("variant") or {}).get("id"),
                     qty,
                     refunded,
                     float(pn["amount"]) if pn.get("amount") else None,
                     pn.get("currencyCode")),
                )
                n_items += 1
        conn.commit()
        print(f"DONE — {n_orders} orders, {n_items} line items ({n_drop} dropped)")


if __name__ == "__main__":
    main()
