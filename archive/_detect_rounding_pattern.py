"""Sample 1,000+ random product prices per store and report ending-fragment frequency
to detect the rounding convention (.99 vs .90 vs .00 vs irregular)."""
import os, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient, ShopConfig
cfg = cfg_mod.load()

Q = """
query ($cursor: String) {
  products(first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges { node { handle priceRangeV2 { minVariantPrice { amount currencyCode } maxVariantPrice { amount } } } }
  }
}
"""

for code in ["SK", "PL", "BA", "MK"]:
    url = os.environ.get(f"ARTMIE_{code}_STORE_URL")
    tok = os.environ.get(f"ARTMIE_{code}_API_TOKEN")
    if not url: continue
    client = ShopifyClient(ShopConfig(store_url=url, api_token=tok, api_version=cfg.shop.api_version))

    cents = Counter()      # last 2 digits after decimal
    integer_endings = Counter()  # last digit before decimal (rounding to .X0?)
    currency = "?"
    n = 0; cursor = None
    while n < 1500:
        d = client.execute(Q, {"cursor": cursor})
        for e in d["products"]["edges"]:
            mvp = e["node"]["priceRangeV2"]["minVariantPrice"]
            currency = mvp["currencyCode"]
            try:
                amt = float(mvp["amount"])
            except: continue
            # Round to 2 dp
            cents[f"{int(round(amt*100))%100:02d}"] += 1
            integer_endings[f"{int(amt)%10}"] += 1
            n += 1
        pi = d["products"]["pageInfo"]
        if not pi["hasNextPage"]: break
        cursor = pi["endCursor"]

    print(f"\n[{code}] currency={currency}  sample n={n}")
    print(f"  Top 8 cent endings (.XX):")
    for k, v in cents.most_common(8):
        print(f"    .{k}  : {v:5d}  ({100*v//n}%)")
EOF