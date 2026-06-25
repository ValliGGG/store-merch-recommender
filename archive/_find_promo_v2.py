"""Find promo collections by broader search per store."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig

cfg = cfg_mod.load()

# Broader queries per store
QUERIES = {
    "SK": 'title:*sale* OR title:*akci* OR title:*zlav* OR title:*vypredaj* OR handle:*zlav* OR handle:*akcia* OR handle:*vypredaj*',
    "MK": 'title:*sale* OR title:*popust* OR title:*namalen* OR title:*akci* OR title:*rasprod* OR handle:*popust* OR handle:*akcija* OR handle:*rasprod* OR handle:*namalen*',
    "BA": 'title:*sale* OR title:*akcij* OR title:*popust* OR title:*rasprod* OR handle:*akcija* OR handle:*popust* OR handle:*rasprod*',
}

LIST_Q = """
query ($q: String!, $cursor: String) {
  collections(first: 50, query: $q, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges { node { id title handle productsCount { count } ruleSet { rules { column relation condition } } } }
  }
}
"""

for code in ["SK", "MK", "BA"]:
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    tok = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    if not url: continue
    shop = ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version)
    client = ShopifyClient(shop)
    print(f"\n[{code}] search: {QUERIES[code]}")
    cursor = None
    while True:
        d = client.execute(LIST_Q, {"q": QUERIES[code], "cursor": cursor})
        for e in d["collections"]["edges"]:
            n = e["node"]
            rules = n.get("ruleSet")
            kind = "SMART" if rules else "MANUAL"
            cnt = n["productsCount"]["count"]
            print(f"  - [{kind:6s}] {n['handle']:35s} {n['title']:35s}  ({cnt} products)")
            if rules:
                for r in rules["rules"]:
                    print(f"        rule: {r['column']} {r['relation']} {r['condition']}")
        pi = d["collections"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]
