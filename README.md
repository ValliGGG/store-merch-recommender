# ARTMiE Recommender

Data-driven merchandising for all ARTMiE Shopify stores. Reads each store's
own order history → SQLite → pushes:

- **Collection sort** — recency-weighted units (order-id window), Artmie pinned
  to slot 3, top sale item to slot 2, out-of-stock demoted to the bottom.
- **FBT metafield** `custom.recommended_products` — lift-based, ≤8 picks/product
  (writes the *existing* theme metafield, so no theme change is needed).
- Plus alternatives, homepage curation, parent-collection sync, and an
  in-stock-first reorder for low-data stores.

## Stores (8)

`load(<store>)` is store-parameterized — each store uses **its own** shop domain
and API token (`ARTMIE_<CODE>_STORE_URL` / `ARTMIE_<CODE>_API_TOKEN`); tokens are
never mixed between stores.

| Code | Store | Mode |
|---|---|---|
| `sk` | artmie.sk (main; also serves AT/HR/DE/GR/IT/SI/**BG** markets via Shopify Markets) | full |
| `cz` | cz-artmie | full |
| `hu` | hu-artmie | full |
| `ro` | ro-artmie | full |
| `mk` | mk-artmie | full |
| `rs` | rs-artmie | full |
| `ba` | ba-artmie | full |
| `pl` | pl-artmie (~112 orders — too few to score) | **borrow** (signal from SK) |

> **BG is not a separate store** — it's a market inside the SK store, so there's
> no `bg` job/token.

- **full** — score from the store's own orders (sort + FBT + extras).
- **borrow** — too little own history; the sort + FBT are derived from
  `borrow_from`'s demand signal mapped onto this catalog **by SKU** (99.8% of PL
  products share an SK SKU). Implemented by `09_borrow_recommendations.py`, which
  runs **inside the source store's job** (the source's order cache is local
  there). The borrow-mode store's own job only does parent sync + homepage.

## Configuration

Everything lives in `config.yaml`:

- `defaults:` — shared pipeline config (scoring weights, brand selector, FBT,
  seasonal windows, `min_orders_floor`).
- `stores:` — per-store credentials env-var names + overrides
  (`handle_filter`, `mode`, `borrow_from`, `pilot_collection`, …).

Key per-store knobs:

- **`handle_filter`** — substring a handle must contain to be eligible. SK uses
  `-sk-` (it hosts foreign-market clones via Markets); expansion stores are
  single-country/standalone, so `null` (whole catalog).
- **`min_orders_floor`** (default 200) — a sort/FBT push is **refused** (clean
  skip, no write) when usable orders in the window fall below this, so a bad
  data day can't flatten a store's merchandising.

## Run a store locally

```bash
# Credentials come from the shared shopify-reports/.env (or a local .env, or
# $ARTMIE_SHARED_ENV). Pick the store with --store (default: sk).

python scripts/02b_refresh_products.py        --store sk   # cache products (+ confirms brand resolves >0)
python scripts/01_initial_export.py           --store sk   # 24-month order backfill
python scripts/03b_compute_bestsellers.py     --store sk --dry-run
python scripts/03b_compute_bestsellers.py     --store sk --collection vsetky-vyrobky   # pilot one collection
python scripts/03b_compute_bestsellers.py     --store sk                                # full push
python scripts/04_compute_recommendations.py  --store sk --dry-run
python scripts/04_compute_recommendations.py  --store sk
```

**First-run order matters:** on a fresh store run `01_initial_export.py`
*before* `02b` (the empty-products guard keeps all line items during backfill),
then refresh products, then sort/FBT. **Always start with `--dry-run` and a
single pilot collection** before a full push.

## Scheduled refresh (GitHub Actions)

`.github/workflows/weekly_refresh.yml` runs **weekly (Sun 02:00 UTC)**, one job
per store (matrix, `fail-fast: false`), each with its own SQLite cache key.

- `workflow_dispatch` → optional **`store`** input runs a single store; **`dry_run`**
  computes without pushing.
- Secrets to create: see [docs/github_secrets.md](docs/github_secrets.md)
  (8 stores × URL+token = 16).
- Projected usage: ~1,000 min/month (under the 2,000 free-minute cap).

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Covers the pure logic: cold-start scoring, dynamic-Easter computus, seasonal
window wrap, occasion mapping, and config deep-merge / store registry.

## Layout

```
config.yaml                 # defaults + per-store registry
scripts/                    # 01..09 production pipeline (09 = borrow signal)
scripts/lib/                # config, shopify_client, db, scoring, seasonal, ...
theme/frequently-bought-together.liquid
tests/                      # unit tests (stdlib unittest)
docs/github_secrets.md      # Actions secrets to create
archive/                    # one-off/experimental scripts (not in the pipeline)
```

## Tunables (in `config.yaml`)

| Setting | Value |
|---|---|
| Backfill window | 24 months |
| Scoring window | 50,000 most-recent orders (by id) |
| Cold-start | 60-day decay × weight 5, capped 25% of #1 |
| Sale boost | `1 + discount × 0.6`; top sale item pinned to slot 2 (≥5% off) |
| Artmie pin | slot 3 (index 2), one per collection |
| Seasonal | in-season ×1.5, off-season ×0.05 |
| Out-of-stock | ×0.0 (sorts to bottom) |
| FBT | ≤8 picks, min co-occurrence 10, 18-month lookback |
| Data-safety floor | 200 usable orders |

## Notes

- GraphQL Admin API only (no REST). All stores are Shopify Plus.
- The brand selector is `custom.znacka == "ARTMiE®"` (the ® matters) — verified
  identical on all 8 stores. `02b` aborts loudly if it resolves zero products.
- Seasonal occasion map + keyword fallback are currently Slovak; on non-SK
  stores they're inert until per-store i18n lands.
