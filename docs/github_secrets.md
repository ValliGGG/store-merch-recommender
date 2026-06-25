# GitHub Actions secrets

The weekly workflow (`.github/workflows/refresh.yml`) needs **one URL +
token pair per store** as repository secrets. Create them under
**Settings → Secrets and variables → Actions → New repository secret**.

## Required secrets (16 total — 8 stores × 2)

| Secret name | Value (example) |
|---|---|
| `ARTMIE_SK_STORE_URL` | `your-main-store.myshopify.com` |
| `ARTMIE_SK_API_TOKEN` | `shpat_…` (SK Admin API token) |
| `ARTMIE_CZ_STORE_URL` | `your-cz-store.myshopify.com` |
| `ARTMIE_CZ_API_TOKEN` | `shpat_…` |
| `ARTMIE_PL_STORE_URL` | `your-pl-store.myshopify.com` |
| `ARTMIE_PL_API_TOKEN` | `shpat_…` |
| `ARTMIE_HU_STORE_URL` | `your-hu-store.myshopify.com` |
| `ARTMIE_HU_API_TOKEN` | `shpat_…` |
| `ARTMIE_RO_STORE_URL` | `your-ro-store.myshopify.com` |
| `ARTMIE_RO_API_TOKEN` | `shpat_…` |
| `ARTMIE_MK_STORE_URL` | `your-mk-store.myshopify.com` |
| `ARTMIE_MK_API_TOKEN` | `shpat_…` |
| `ARTMIE_RS_STORE_URL` | `your-rs-store.myshopify.com` |
| `ARTMIE_RS_API_TOKEN` | `shpat_…` |
| `ARTMIE_BA_STORE_URL` | `your-ba-store.myshopify.com` |
| `ARTMIE_BA_API_TOKEN` | `shpat_…` |

Each value is the store's own `*_STORE_URL` / `*_API_TOKEN` from your local
shared `.env` (kept out of the repo via `.gitignore`).

## Notes

- **No `ARTMIE_BG_*`** — BG is a market inside the SK store (Shopify Markets),
  not a standalone Shopify store.
- Each token needs **read_products, write_products, read_orders,
  read_inventory** scopes (and the collection/metafield write scopes the
  pipeline already uses on SK).
- The workflow exposes all 16 to every job, but each job runs exactly one store
  via `--store` and `config.py` reads only that store's pair — tokens are never
  used cross-store.

## Quick bulk-create with the `gh` CLI

From a machine that has the shared `.env` and `gh` authenticated to the repo:

```bash
cd artmie_recomander
for code in SK CZ PL HU RO MK RS BA; do
  for suf in STORE_URL API_TOKEN; do
    name="ARTMIE_${code}_${suf}"
    val=$(grep -E "^${name}=" "$SHARED_ENV" | head -1 | cut -d= -f2-)   # SHARED_ENV=path to your shared .env
    [ -n "$val" ] && gh secret set "$name" --body "$val" --repo ValliGGG/store-merch-recommender
  done
done
```
