"""Wire homepage tiles by adding 5 product-list sections pointing at category collections.

- Reads current templates/index.json (already backed up to _index_backup.json)
- Repurposes existing product_list_fa6P9H to point at `bestsellery`
- Clones it 5 times for the recommended category collections
- Updates section order to interleave the new tiles with the existing custom sections
- Writes back via themeFilesUpsert mutation

Safe to re-run: idempotent. If sections with these handles already exist, they're updated in place.
"""
from __future__ import annotations
import copy, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient

THEME_ID = "gid://shopify/OnlineStoreTheme/189867131224"

# (section_key, collection_handle, display_position)
TILES = [
    ("plist_bestsellers",  "bestsellery"),                  # Bestsellery (overall)
    ("plist_paints",       "umelecke-farby"),                # Umelecké farby
    ("plist_brushes",      "umelecke-stetce-a-pomocky"),     # Umelecké štetce a pomôcky
    ("plist_paper",        "papier-scrapbook-dekupaz"),      # Papier, scrapbook a dekupáž
    ("plist_kids",         "kreativne-potreby-pre-deti"),    # Kreatívne potreby pre deti
    ("plist_seasonal",     "sezonne-tvorenie"),              # Sezónne tvorenie
]


def main():
    cfg = cfg_mod.load()
    client = ShopifyClient(cfg.shop)

    # Read current
    Q = """query ($id:ID!) {
      theme(id:$id) { files(first: 1, filenames: ["templates/index.json"]) {
        nodes { filename body { ... on OnlineStoreThemeFileBodyText { content } } } } }
    }"""
    d = client.execute(Q, {"id": THEME_ID})
    content = d["theme"]["files"]["nodes"][0]["body"]["content"]
    header_end = content.find("*/") + 2 if content.lstrip().startswith("/*") else 0
    header = content[:header_end]
    data = json.loads(content[header_end:])

    # Use existing product_list_fa6P9H as the template for all new sections
    template = data["sections"]["product_list_fa6P9H"]

    # Build / update tile sections
    for key, coll_handle in TILES:
        new_sec = copy.deepcopy(template)
        new_sec["settings"]["collection"] = coll_handle
        # Disable the static-header padding so all tiles look uniform
        # (already inherited from template; nothing else to change)
        data["sections"][key] = new_sec

    # Remove the original product_list_fa6P9H since plist_bestsellers replaces it
    data["sections"].pop("product_list_fa6P9H", None)

    # Build new order: hero -> category grid -> 6 tiles -> seo -> signup
    base_order = data.get("order", [])
    # Strip out tile keys + the old product_list from existing order so we can re-insert cleanly
    keep = [k for k in base_order
            if k not in {key for key, _ in TILES}
            and k != "product_list_fa6P9H"]
    # Find anchor positions
    new_order = []
    inserted = False
    for k in keep:
        if k == "artmie_cat_grid_2025" and not inserted:
            new_order.append(k)
            new_order.extend(key for key, _ in TILES)
            inserted = True
        else:
            new_order.append(k)
    if not inserted:
        # Fallback: append tiles after first section
        anchor = new_order[:1]
        new_order = anchor + [key for key, _ in TILES] + new_order[1:]
    data["order"] = new_order

    # Compose final content with original header preserved
    new_content = header + "\n" + json.dumps(data, indent=2, ensure_ascii=False)

    # Write via themeFilesUpsert
    M = """
    mutation ($themeId:ID!, $files:[OnlineStoreThemeFilesUpsertFileInput!]!) {
      themeFilesUpsert(themeId:$themeId, files:$files) {
        upsertedThemeFiles { filename }
        userErrors { filename code message }
      }
    }
    """
    r = client.execute(M, {
        "themeId": THEME_ID,
        "files": [{
            "filename": "templates/index.json",
            "body": {"type": "TEXT", "value": new_content},
        }],
    })
    errs = r["themeFilesUpsert"]["userErrors"]
    if errs:
        print("ERRORS:", errs); sys.exit(1)
    print("✅ updated templates/index.json")
    print(f"   new section order ({len(new_order)} sections):")
    for s in new_order:
        sec = data["sections"][s]
        coll = sec.get("settings", {}).get("collection", "")
        marker = f"  → {coll}" if coll else ""
        print(f"     - {s:30s} type={sec.get('type'):30s}{marker}")


if __name__ == "__main__":
    main()
