"""Show before/after for one collection — no writes."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod, db as db_mod, seasonal
from lib.shopify_client import ShopifyClient
from datetime import datetime, timezone

import importlib.util
spec = importlib.util.spec_from_file_location(
    "_bs", Path(__file__).resolve().parent / "scripts" / "03b_compute_bestsellers.py"
)
bs = importlib.util.module_from_spec(spec); spec.loader.exec_module(bs)

cfg = cfg_mod.load()
client = ShopifyClient(cfg.shop)
conn = db_mod.connect(cfg.db_path)
db_mod.ensure_schema(conn)
today = datetime.now(timezone.utc).date()

handle = sys.argv[1] if len(sys.argv) > 1 else "bestsellery"

# Find the collection
coll = None
cursor = None
while True:
    d = client.execute(bs.LIST_COLLECTIONS_Q, {"cursor": cursor})
    for e in d["collections"]["edges"]:
        if e["node"]["handle"] == handle:
            coll = e["node"]; break
    pi = d["collections"]["pageInfo"]
    if coll or not pi["hasNextPage"]: break
    cursor = pi["endCursor"]

if not coll:
    print(f"collection {handle!r} not found"); sys.exit(1)

print(f"Collection: {coll['title']!r}  ({coll['handle']})  sortOrder={coll['sortOrder']}")

before = bs.fetch_collection_product_ids(client, coll["id"])
print(f"Total products in collection: {len(before)}")

# Hydrate meta
placeholders = ",".join("?" * len(before))
rows = conn.execute(
    f"SELECT * FROM products WHERE id IN ({placeholders})", before
).fetchall()
meta = {r["id"]: dict(r) for r in rows}

kept = [pid for pid in before
        if pid in meta
           and (meta[pid].get("status") or "").upper() == "ACTIVE"]
print(f"After filter (active + cached): {len(kept)}")

# Compute scores
bs.ensure_recent_orders_table(conn, int(cfg.scoring["recent_orders_window"]))
scores = bs.compute_scores(conn, kept, cfg, today)
ranked = sorted(kept, key=lambda p: (-scores.get(p, 0.0), meta[p].get("title") or ""))
with_sale = bs.apply_sale_pin(
    ranked, meta,
    pin_pos=int(cfg.scoring.get("sale_pin_position", 1)),
    min_disc=float(cfg.scoring.get("sale_pin_min_discount", 0.05)),
)
with_pin = bs.apply_artmie_pin(with_sale, meta, int(cfg.artmie_brand["pin_position"]))

print("\nBEFORE (current live order, top 15):")
for i, pid in enumerate(before[:15], 1):
    m = meta.get(pid, {})
    flag = "★" if m.get("is_artmie") else " "
    print(f"  {i:2d}.{flag} {(m.get('title') or '?')[:65]}")

print("\nAFTER  (proposed order, top 15):")
for i, pid in enumerate(with_pin[:15], 1):
    m = meta[pid]
    artmie_flag = "★" if m.get("is_artmie") else " "
    disc = m.get("discount_pct") or 0
    sale_flag = f"-{disc*100:2.0f}%" if disc > 0 else "    "
    sc = scores.get(pid, 0.0)
    print(f"  {i:2d}.{artmie_flag}{sale_flag}  score={sc:6.0f}  {m['title'][:50]}")
