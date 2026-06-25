"""Update existing homepage product-list tiles to show 12 products instead of 8."""
from __future__ import annotations
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient

THEME_ID = "gid://shopify/OnlineStoreTheme/189867131224"
TILE_KEYS = {
    "plist_bestsellers", "plist_paints", "plist_brushes",
    "plist_paper", "plist_kids", "plist_seasonal",
}
NEW_MAX = 12


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

    changed = 0
    for key in TILE_KEYS:
        sec = data["sections"].get(key)
        if not sec:
            print(f"  ! section {key} not found")
            continue
        old = sec.setdefault("settings", {}).get("max_products")
        sec["settings"]["max_products"] = NEW_MAX
        if old != NEW_MAX:
            changed += 1
            print(f"  {key}: max_products {old} -> {NEW_MAX}")

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
    print(f"\n✅ updated {changed} tiles to show {NEW_MAX} products")


if __name__ == "__main__":
    main()
