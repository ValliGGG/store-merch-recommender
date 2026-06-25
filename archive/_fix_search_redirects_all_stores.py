"""Fix + extend search redirects across all 4 stores.

Two fixes:
1. Shopify URL-encodes spaces as `+` (not `%20` from urllib.quote). Old SK redirects
   used `%20` and never fired. Re-create with `+`-encoded paths AND `%20` paths
   (both, since some clients use either).
2. Add per-store translated terms (PL/BA/MK), since the original SK script only
   covered SK queries.

Idempotent — checks existing redirects, only creates missing ones.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from lib import shopify_client
from lib.shopify_client import ShopConfig

# Per-store query → target collection mapping
REDIRECTS_BY_STORE = {
    "SK": [
        ("akrylové farby", "umelecke-farby"),
        ("akrylove farby", "umelecke-farby"),
        ("akrylová farba", "umelecke-farby"),
        ("akryl",          "umelecke-farby"),
        ("acrylic",        "umelecke-farby"),
        ("acrylic paint",  "umelecke-farby"),
        ("acrylic paints", "umelecke-farby"),
        ("olejové farby",  "umelecke-farby"),
        ("olejova farba",  "umelecke-farby"),
        ("olej",           "umelecke-farby"),
        ("oil paint",      "umelecke-farby"),
        ("vodové farby",   "umelecke-farby"),
        ("akvarel",        "umelecke-farby"),
        ("akvarelové farby","umelecke-farby"),
        ("watercolor",     "umelecke-farby"),
        ("štetce",         "umelecke-stetce-a-pomocky"),
        ("stetce",         "umelecke-stetce-a-pomocky"),
        ("štetec",         "umelecke-stetce-a-pomocky"),
        ("stetec",         "umelecke-stetce-a-pomocky"),
        ("brush",          "umelecke-stetce-a-pomocky"),
        ("brushes",        "umelecke-stetce-a-pomocky"),
        ("plátno",         "maliarske-platna"),
        ("platno",         "maliarske-platna"),
        ("canvas",         "maliarske-platna"),
        ("maliarske plátno","maliarske-platna"),
        ("papier",         "papier-scrapbook-dekupaz"),
        ("papier kresliaci","papiere-a-pomocky-kreslenie"),
        ("paper",          "papier-scrapbook-dekupaz"),
        ("pastely",        "pastely-a-fixy"),
        ("pastel",         "pastely-a-fixy"),
        ("ceruzky",        "ceruzky-a-grafika"),
        ("ceruzka",        "ceruzky-a-grafika"),
        ("pencil",         "ceruzky-a-grafika"),
        ("scrapbook",      "scrapbooking"),
        ("dekupáž",        "dekupaz-servitkovanie"),
        ("dekupaz",        "dekupaz-servitkovanie"),
        ("modelovanie",    "modelovanie-a-odlievanie"),
        ("vianoce",        "vianoce"),
        ("vianočný",       "vianoce"),
        ("christmas",      "vianoce"),
        ("valentín",       "valentin"),
        ("valentin",       "valentin"),
        ("svadba",         "svadba"),
        ("artmie",         "artmie-r"),
    ],
    "PL": [
        ("farby akrylowe", "farby-artystyczne"),
        ("akryl",          "farby-artystyczne"),
        ("acrylic",        "farby-artystyczne"),
        ("farby olejne",   "farby-artystyczne"),
        ("olej",           "farby-artystyczne"),
        ("akwarele",       "farby-artystyczne"),
        ("akwarela",       "farby-artystyczne"),
        ("watercolor",     "farby-artystyczne"),
        ("pędzle",         "pedzle-artystyczne-i-akcesoria"),
        ("pedzle",         "pedzle-artystyczne-i-akcesoria"),
        ("pędzel",         "pedzle-artystyczne-i-akcesoria"),
        ("pedzel",         "pedzle-artystyczne-i-akcesoria"),
        ("brush",          "pedzle-artystyczne-i-akcesoria"),
        ("podobrazia",     "podobrazia-malarskie"),
        ("płótno",         "podobrazia-malarskie"),
        ("plotno",         "podobrazia-malarskie"),
        ("canvas",         "podobrazia-malarskie"),
        ("papier",         "papier-i-arkusze-rysunkowe"),
        ("paper",          "papier-i-arkusze-rysunkowe"),
        ("pastele",        "pastele-i-markery"),
        ("ołówki",         "olowki-i-grafika"),
        ("olowki",         "olowki-i-grafika"),
        ("ołówek",         "olowki-i-grafika"),
        ("pencil",         "olowki-i-grafika"),
        ("scrapbooking",   "scrapbooking"),
        ("decoupage",      "scrapbooking"),
        ("modelowanie",    "modelowanie"),
        ("święta",         "dekoracje-sezonowe"),
        ("swieta",         "dekoracje-sezonowe"),
        ("christmas",      "dekoracje-sezonowe"),
        ("walentynki",     "dekoracje-sezonowe"),
        ("valentine",      "dekoracje-sezonowe"),
    ],
    "BA": [
        ("akrilne boje",   "umjetnicke-boje"),
        ("akril",          "umjetnicke-boje"),
        ("acrylic",        "umjetnicke-boje"),
        ("uljane boje",    "umjetnicke-boje"),
        ("akvarelne boje", "umjetnicke-boje"),
        ("akvarel",        "umjetnicke-boje"),
        ("watercolor",     "umjetnicke-boje"),
        ("kistovi",        "umjetnicki-kistovi-i-pribor"),
        ("kist",           "umjetnicki-kistovi-i-pribor"),
        ("brush",          "umjetnicki-kistovi-i-pribor"),
        ("platna",         "slikarska-platna"),
        ("platno",         "slikarska-platna"),
        ("canvas",         "slikarska-platna"),
        ("papir",          "papir-scrapbook-dekupaz"),
        ("paper",          "papir-scrapbook-dekupaz"),
        ("pasteli",        "pasteli-i-flomasteri"),
        ("olovke",         "olovke-i-grafika"),
        ("olovka",         "olovke-i-grafika"),
        ("scrapbook",      "papir-scrapbook-dekupaz"),
        ("modeliranje",    "modeliranje-i-odlijevanje"),
        ("bozic",          "sezonsko-stvaralastvo"),
        ("božić",          "sezonsko-stvaralastvo"),
        ("christmas",      "sezonsko-stvaralastvo"),
    ],
    "MK": [
        ("акрилни бои",    "umetnicki-boi"),
        ("akrilni boi",    "umetnicki-boi"),
        ("acrylic",        "umetnicki-boi"),
        ("маслени бои",    "umetnicki-boi"),
        ("акварели",       "umetnicki-boi"),
        ("watercolor",     "umetnicki-boi"),
        ("четки",          "umetnicki-cetki-i-pribor"),
        ("cetki",          "umetnicki-cetki-i-pribor"),
        ("brush",          "umetnicki-cetki-i-pribor"),
        ("платна",         "slikarski-platna"),
        ("platna",         "slikarski-platna"),
        ("canvas",         "slikarski-platna"),
        ("хартија",        "hartija-skrapbuk-decoupage"),
        ("hartija",        "hartija-skrapbuk-decoupage"),
        ("paper",          "hartija-skrapbuk-decoupage"),
        ("божиќ",          "sezonska-izrada"),
        ("bozic",          "sezonska-izrada"),
        ("christmas",      "sezonska-izrada"),
    ],
}


def encode_for_redirect(q: str) -> list[str]:
    """Return both `+` and `%20` encoded paths since clients vary."""
    from urllib.parse import quote, quote_plus
    plus = quote_plus(q)              # spaces -> +
    pct  = quote(q, safe="")          # spaces -> %20
    paths = [f"/search?q={plus}"]
    if pct != plus:
        paths.append(f"/search?q={pct}")
    return paths


def main():
    LIST_Q = """
    query ($cursor: String) {
      urlRedirects(first: 250, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        edges { node { path target } }
      }
    }
    """
    M = """
    mutation Create($input: UrlRedirectInput!) {
      urlRedirectCreate(urlRedirect: $input) {
        urlRedirect { id }
        userErrors { field message }
      }
    }
    """

    summary = {}
    for store, items in REDIRECTS_BY_STORE.items():
        url = os.environ.get(f"ARTMIE_{store}_STORE_URL")
        tok = os.environ.get(f"ARTMIE_{store}_API_TOKEN")
        if not url:
            print(f"\n=== {store}: missing env, skip"); continue
        client = shopify_client.ShopifyClient(ShopConfig(store_url=url, api_token=tok, api_version="2025-01"))
        print(f"\n=== {store} ({url}) ===")

        existing: set[str] = set()
        cursor = None
        while True:
            d = client.execute(LIST_Q, {"cursor": cursor})
            for e in d["urlRedirects"]["edges"]:
                existing.add(e["node"]["path"].lower())
            pi = d["urlRedirects"]["pageInfo"]
            if not pi["hasNextPage"]: break
            cursor = pi["endCursor"]
        print(f"  existing redirects: {len(existing)}")

        created = 0
        skipped = 0
        failed  = 0
        for query, handle in items:
            target = f"/collections/{handle}"
            for path in encode_for_redirect(query):
                if path.lower() in existing:
                    skipped += 1
                    continue
                try:
                    d = client.execute(M, {"input": {"path": path, "target": target}})
                    errs = d["urlRedirectCreate"]["userErrors"]
                    if errs:
                        msg = errs[0].get("message", "")
                        if "already exists" in msg.lower() or "taken" in msg.lower():
                            skipped += 1
                        else:
                            failed += 1
                            print(f"    ✗ {path} -> {target}: {msg}")
                    else:
                        created += 1
                except Exception as e:
                    failed += 1
                    print(f"    ✗ {path} -> {target}: {e}")
        summary[store] = (created, skipped, failed)
        print(f"  created={created} skipped={skipped} failed={failed}")

    print("\n=== summary ===")
    for s, (c, sk, f) in summary.items():
        print(f"  {s}: created={c} skipped={sk} failed={f}")


if __name__ == "__main__":
    main()
