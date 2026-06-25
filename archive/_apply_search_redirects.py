"""Apply search redirects for top SK art-supply queries.

Until Search & Discovery is installed (manual OAuth required), the next-best
thing is to redirect common search queries to their best category collection
page — which is already sorted by best-sellers + Artmie pin via 03b.

`/search?q=akrylové farby` → 302 → `/collections/akrylove-farby`

Idempotent — checks for existing redirect at the same `path`, only creates if absent.
"""
from __future__ import annotations
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import config as cfg_mod
from lib.shopify_client import ShopifyClient

# (search query → target collection handle)
REDIRECTS = [
    ("akrylové farby",  "umelecke-farby"),
    ("akrylove farby",  "umelecke-farby"),
    ("olejové farby",   "umelecke-farby"),
    ("vodové farby",    "umelecke-farby"),
    ("akvarelové farby", "umelecke-farby"),
    ("štetce",          "umelecke-stetce-a-pomocky"),
    ("stetce",          "umelecke-stetce-a-pomocky"),
    ("plátno",          "papiere-a-vykresy"),
    ("platno",          "papiere-a-vykresy"),
    ("papier",          "papier-scrapbook-dekupaz"),
    ("pastely",         "pastely-a-fixy"),
    ("ceruzky",         "ceruzky-a-grafika"),
    ("scrapbook",       "scrapbooking"),
    ("dekupáž",         "dekupaz-servitkovanie"),
    ("dekupaz",         "dekupaz-servitkovanie"),
    ("modelovanie",     "modelovanie-a-odlievanie"),
    ("dekorácie",       "dekoracny-material"),
    ("dekoracie",       "dekoracny-material"),
    ("vianoce",         "vianoce"),
    ("valentín",        "valentin"),
    ("valentin",        "valentin"),
    ("svadba",          "svadba"),
    ("kresliace potreby", "kreslarske-potreby"),
    ("artmie",          "artmie-r"),
    ("KREUL",           "kreul"),
    ("Royal & Langnickel", "umelecke-stetce-a-pomocky"),
]


def main():
    cfg = cfg_mod.load()
    client = ShopifyClient(cfg.shop)

    # Pull existing redirects to avoid duplicates
    print("loading existing redirects...")
    existing: set[str] = set()
    cursor = None
    while True:
        Q = """
        query ($cursor: String) {
          urlRedirects(first: 250, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            edges { node { path target } }
          }
        }
        """
        d = client.execute(Q, {"cursor": cursor})
        for e in d["urlRedirects"]["edges"]:
            existing.add(e["node"]["path"].lower())
        pi = d["urlRedirects"]["pageInfo"]
        if not pi["hasNextPage"]:
            break
        cursor = pi["endCursor"]
    print(f"  {len(existing)} existing redirects")

    M = """
    mutation Create($input: UrlRedirectInput!) {
      urlRedirectCreate(urlRedirect: $input) {
        urlRedirect { id path target }
        userErrors { field message }
      }
    }
    """

    created = 0
    skipped = 0
    failed = 0
    for query, handle in REDIRECTS:
        path = f"/search?q={quote(query)}"
        if path.lower() in existing:
            skipped += 1
            continue
        target = f"/collections/{handle}"
        try:
            d = client.execute(M, {"input": {"path": path, "target": target}})
            errs = d["urlRedirectCreate"]["userErrors"]
            if errs:
                print(f"  ✗ {query!r}: {errs}")
                failed += 1
            else:
                created += 1
                print(f"  ✓ {query!r} → {target}")
        except Exception as e:
            print(f"  ✗ {query!r}: {e}")
            failed += 1

    print(f"\nDONE — created={created} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    main()
