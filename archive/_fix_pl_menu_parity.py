"""Fix PL menu so it mirrors SK's 27-parent structure.

PL currently has 2 menu items that share URL with their parent, causing dedupe
to merge them (PL = 25 parents instead of 27):

  1. "Ołówki i materiały rysunkowe" -> /collections/rysowanie  (same as parent "Rysunek")
  2. "Papiery i akcesoria" -> /collections/papier-i-arkusze-rysunkowe  (same as sibling "Papiery i bloki")

Fix:
  - Create new PL collections: `olowki-i-grafika`, `papiery-i-akcesoria-rysunkowe`
  - Publish them to Online Store
  - Update PL menu to point those items to the new collections
  - 07 will auto-populate them from their grandchildren on next run
"""
from __future__ import annotations
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import shopify_client
from lib.shopify_client import ShopConfig

url = os.environ["ARTMIE_PL_STORE_URL"]; tok = os.environ["ARTMIE_PL_API_TOKEN"]
client = shopify_client.ShopifyClient(ShopConfig(store_url=url, api_token=tok, api_version="2025-01"))

# 1. Create the two missing collections
TO_CREATE = [
    {"handle": "olowki-i-grafika",                  "title": "Ołówki i materiały rysunkowe"},
    {"handle": "papiery-i-akcesoria-rysunkowe",     "title": "Papiery i akcesoria"},
]

CREATE_M = """
mutation ($input: CollectionInput!) {
  collectionCreate(input: $input) {
    collection { id handle title }
    userErrors { field message }
  }
}
"""

CHECK_Q = """
query ($h:String!) { collectionByHandle(handle:$h) { id handle title } }
"""

PUBLISH_M = """
mutation ($id: ID!, $inputs:[PublicationInput!]!) {
  publishablePublish(id:$id, input:$inputs) { userErrors { field message } }
}
"""
PL_ONLINE_STORE = "gid://shopify/Publication/174579581172"

new_gids = {}
for c in TO_CREATE:
    existing = client.execute(CHECK_Q, {"h": c["handle"]}).get("collectionByHandle")
    if existing:
        print(f"  {c['handle']:40s} already exists ({existing['id']})")
        new_gids[c["handle"]] = existing["id"]
        continue
    d = client.execute(CREATE_M, {"input": {
        "handle": c["handle"], "title": c["title"], "sortOrder": "MANUAL",
        "descriptionHtml": "Auto-managed parent — populated daily from descendant menu collections.",
    }})
    errs = d["collectionCreate"]["userErrors"]
    if errs:
        print(f"  ERROR creating {c['handle']}: {errs}"); sys.exit(1)
    gid = d["collectionCreate"]["collection"]["id"]
    new_gids[c["handle"]] = gid
    # Publish
    client.execute(PUBLISH_M, {"id": gid, "inputs": [{"publicationId": PL_ONLINE_STORE}]})
    print(f"  ✅ created+published {c['handle']} -> {gid}")

# 2. Read the menu and find the 2 items that need updating
MENU_Q = """
{
  menus(first: 30) {
    edges { node { id handle items { ...M items { ...M items { ...M items { ...M } } } } } }
  }
}
fragment M on MenuItem { id title type url resourceId items { id } }
"""
d = client.execute(MENU_Q)
menu = next(e["node"] for e in d["menus"]["edges"] if e["node"]["handle"] == "artmie-menu")

# Walk and find items by title — return list of (parent_path, item)
matches = {}  # title -> item
def walk(items, path=()):
    for item in items or []:
        matches.setdefault(item["title"], item)
        walk(item.get("items"), path + (item["title"],))
walk(menu["items"])

target_updates = [
    ("Ołówki i materiały rysunkowe", "/collections/olowki-i-grafika", new_gids["olowki-i-grafika"]),
    ("Papiery i akcesoria",          "/collections/papiery-i-akcesoria-rysunkowe", new_gids["papiery-i-akcesoria-rysunkowe"]),
]

# Helper to walk nested items dropping `items` field for menuUpdate input shape
def to_input(items):
    out = []
    for it in items or []:
        # Update target items in place
        new_url = it.get("url")
        new_type = it.get("type")
        new_resource_id = it.get("resourceId")
        for tgt_title, tgt_url, tgt_gid in target_updates:
            if it.get("title") == tgt_title:
                new_url = tgt_url
                new_type = "COLLECTION"
                new_resource_id = tgt_gid
        rec = {
            "id": it["id"],
            "title": it["title"],
            "type": new_type,
            "url": new_url,
        }
        if new_resource_id:
            rec["resourceId"] = new_resource_id
        if it.get("items"):
            rec["items"] = to_input(it["items"])
        out.append(rec)
    return out

input_items = to_input(menu["items"])

UPDATE_M = """
mutation ($id: ID!, $title: String!, $handle: String!, $items: [MenuItemUpdateInput!]!) {
  menuUpdate(id:$id, title:$title, handle:$handle, items:$items) {
    menu { id handle title }
    userErrors { field message }
  }
}
"""

# Re-fetch menu to get its title
menu_meta = client.execute("query ($id:ID!){ menu(id:$id){ id handle title } }", {"id": menu["id"]})["menu"]

print(f"\nupdating menu '{menu['handle']}' ({menu['id']})...")
d = client.execute(UPDATE_M, {"id": menu["id"], "title": menu_meta["title"], "handle": menu_meta["handle"], "items": input_items})
errs = d["menuUpdate"]["userErrors"]
if errs:
    print(f"  ERRORS: {errs}"); sys.exit(1)
print(f"  ✅ menu updated. Verify at https://{url}/admin/menus")

print("\nDONE — re-run scripts/07_sync_parent_collections.py --store pl to populate new parents")
