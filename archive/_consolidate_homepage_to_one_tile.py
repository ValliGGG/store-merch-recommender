"""Reduce homepage to a single Bestsellery product-list (12 products), removing the 5 secondary tiles
(per user 2026-04-26: 'I need only 12 products on the main page')."""
from __future__ import annotations
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient

THEME_ID = "gid://shopify/OnlineStoreTheme/189867131224"
KEEP = "plist_bestsellers"
REMOVE = {"plist_paints", "plist_brushes", "plist_paper", "plist_kids", "plist_seasonal"}


def main():
    cfg = cfg_mod.load()
    client = ShopifyClient(cfg.shop)

    Q = """query ($id:ID!) {
      theme(id:$id) { files(first: 1, filenames: ["templates/index.json"]) {
        nodes { body { ... on OnlineStoreThemeFileBodyText { content } } } } }
    }"""
    d = client.execute(Q, {"id": THEME_ID})
    content = d["theme"]["files"]["nodes"][0]["body"]["content"]
    header_end = content.find("*/") + 2 if content.lstrip().startswith("/*") else 0
    header = content[:header_end]
    data = json.loads(content[header_end:])

    # Backup before changing
    Path("_index_backup_pre_consolidate.json").write_text(content, encoding="utf-8")

    # Remove sections
    removed = []
    for key in list(REMOVE):
        if data["sections"].pop(key, None) is not None:
            removed.append(key)

    # Remove from order
    data["order"] = [s for s in data.get("order", []) if s not in REMOVE]

    new_content = header + "\n" + json.dumps(data, indent=2, ensure_ascii=False)

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
        "files": [{"filename": "templates/index.json", "body": {"type": "TEXT", "value": new_content}}],
    })
    errs = r["themeFilesUpsert"]["userErrors"]
    if errs:
        print("ERRORS:", errs); sys.exit(1)

    print(f"✅ removed {len(removed)} sections: {removed}")
    print(f"\nFinal section order ({len(data['order'])} sections):")
    for s in data["order"]:
        sec = data["sections"][s]
        coll = sec.get("settings", {}).get("collection", "")
        marker = f"  → {coll}" if coll else ""
        print(f"  - {s:30s} type={sec.get('type'):30s}{marker}")


if __name__ == "__main__":
    main()
