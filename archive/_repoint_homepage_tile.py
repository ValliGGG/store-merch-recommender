"""Repoint the homepage's single product-list tile from `bestsellery` to `homepage-curated`."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient

THEME_ID = "gid://shopify/OnlineStoreTheme/189867131224"

cfg = cfg_mod.load(); client = ShopifyClient(cfg.shop)

Q = """query ($id:ID!) {
  theme(id:$id) { files(first:1, filenames:["templates/index.json"]) {
    nodes { body { ... on OnlineStoreThemeFileBodyText { content } } } } }
}"""
d = client.execute(Q, {"id": THEME_ID})
content = d["theme"]["files"]["nodes"][0]["body"]["content"]
header_end = content.find("*/")+2 if content.lstrip().startswith("/*") else 0
header = content[:header_end]
data = json.loads(content[header_end:])

sec = data["sections"]["plist_bestsellers"]
old = sec["settings"].get("collection")
sec["settings"]["collection"] = "homepage-curated"
sec["settings"]["max_products"] = 12
print(f"plist_bestsellers: collection {old!r} -> 'homepage-curated' (max=12)")

new_content = header + "\n" + json.dumps(data, indent=2, ensure_ascii=False)

M = """mutation ($themeId:ID!, $files:[OnlineStoreThemeFilesUpsertFileInput!]!) {
  themeFilesUpsert(themeId:$themeId, files:$files) {
    upsertedThemeFiles { filename }
    userErrors { filename code message }
  }
}"""
r = client.execute(M, {"themeId": THEME_ID, "files":[{"filename":"templates/index.json","body":{"type":"TEXT","value":new_content}}]})
errs = r["themeFilesUpsert"]["userErrors"]
if errs: print("ERRORS:", errs); sys.exit(1)
print("✅ updated templates/index.json")
