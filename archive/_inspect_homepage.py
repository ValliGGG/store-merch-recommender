"""Inspect what sections the SK homepage template uses, so we know
where to wire up homepage bestsellers-per-category."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient

cfg = cfg_mod.load()
client = ShopifyClient(cfg.shop)

# Find the published theme
THEMES_Q = """
{ themes(first: 20) { edges { node { id name role } } } }
"""
d = client.execute(THEMES_Q)
published = None
for e in d["themes"]["edges"]:
    if e["node"]["role"] == "MAIN":
        published = e["node"]; break
print(f"published theme: {published}")

if not published:
    sys.exit(0)

# Per memory, SK homepage is at templates/index.context.sk.json (or just templates/index.json)
# List theme assets matching index*
ASSETS_Q = """
query Files($id: ID!, $cursor: String) {
  theme(id: $id) {
    files(first: 100, after: $cursor, filenames: ["templates/index.json","templates/index.context.sk.json"]) {
      pageInfo { hasNextPage endCursor }
      nodes {
        filename
        size
        body { ... on OnlineStoreThemeFileBodyText { content } }
      }
    }
  }
}
"""
d = client.execute(ASSETS_Q, {"id": published["id"]})
nodes = d["theme"]["files"]["nodes"]
print(f"\nfound {len(nodes)} matching files")

for f in nodes:
    print(f"\n=== {f['filename']}  size={f['size']} ===")
    body = (f.get("body") or {}).get("content", "")
    # Strip leading /* ... */ comment block (Horizon theme adds this header)
    if body.lstrip().startswith("/*"):
        end = body.find("*/")
        if end > 0:
            body = body[end + 2 :]
    try:
        data = json.loads(body)
    except Exception as e:
        print(f"  not JSON: {e}")
        print(body[:800])
        continue
    sections = data.get("sections", {})
    order = data.get("order", [])
    print(f"  sections in order ({len(order)}):")
    for sid in order:
        s = sections.get(sid, {})
        stype = s.get("type", "?")
        # Look for collection/product references
        settings = s.get("settings", {}) or {}
        coll = settings.get("collection") or settings.get("collection_handle")
        prods = settings.get("products") or settings.get("product_list")
        marker = ""
        if coll:
            marker = f"  collection={coll!r}"
        elif prods:
            n = len(prods) if isinstance(prods, list) else "?"
            marker = f"  products=[{n}]"
        print(f"    - {sid:30s} type={stype:30s} {marker}")
