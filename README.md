# Store Merchandising Recommender

Data-driven merchandising for a multi-store Shopify setup. Reads each store's
own order history → SQLite → pushes:

- **Collection sort** — recency-weighted units (order-id window), a configurable
  house brand pinned to slot 3, top sale item to slot 2, out-of-stock demoted to
  the bottom.
- **FBT metafield** `custom.recommended_products` — lift-based, ≤8 picks/product
  (writes an *existing* theme metafield, so no theme change is needed).
- Plus alternatives, homepage curation, parent-collection sync, and an
  in-stock-first reorder for low-data stores.

## Stores

`load(<store>)` is store-parameterized — each store uses **its own** shop domain
and API token (`*_STORE_URL` / `*_API_TOKEN` env vars); tokens are never mixed
between stores. Stores are configured in `config.yaml` under `stores:` using
abstract two-letter codes; add/remove entries freely.

Each store runs in one of two modes:

- **full** — the store has its own order history → score sort + FBT from it.
- **borrow** — the store has too little history of its own; its sort + FBT are
  derived from another store's demand signal mapped onto this catalog **by SKU**
  (works when catalogs mirror each other). Implemented by
  `09_borrow_recommendations.py`, which runs **inside the source store's job**
  (the source's order cache is local there). The borrow-mode store's own job
  only does parent sync + homepage.

## Configuration

Everything lives in `config.yaml`:

- `defaults:` — shared pipeline config (scoring weights, brand selector, FBT,
  seasonal windows, `min_orders_floor`).
- `stores:` — per-store env-var names + overrides (`handle_filter`, `mode`,
  `borrow_from`, `pilot_collection`, localized seasonal occasion maps, …).

Key per-store knobs:

- **`handle_filter`** — substring a handle must contain to be eligible (e.g. a
  market suffix when one store hosts several markets via Shopify Markets). Set to
  `null` for single-catalog stores (process everything).
- **`min_orders_floor`** (default 200) — a sort/FBT push is **refused** (clean
  skip, no write) when usable orders in the window fall below this, so a bad
  data day can't flatten a store's merchandising.

## Run a store locally

```bash
# Credentials come from a local .env (or $STORE_SHARED_ENV). Pick the store
# with --store (default: the first/primary store).

python scripts/02b_refresh_products.py        --store sk   # cache products (+ confirms brand resolves >0)
python scripts/01_initial_export.py           --store sk   # 24-month order backfill
python scripts/03b_compute_bestsellers.py     --store sk --dry-run
python scripts/03b_compute_bestsellers.py     --store sk --collection <handle>   # pilot one collection
python scripts/03b_compute_bestsellers.py     --store sk                          # full push
python scripts/04_compute_recommendations.py  --store sk --dry-run
python scripts/04_compute_recommendations.py  --store sk
```

**First-run order matters:** on a fresh store run `01_initial_export.py`
*before* `02b` (the empty-products guard keeps all line items during backfill),
then refresh products, then sort/FBT. **Always start with `--dry-run` and a
single pilot collection** before a full push.

## Scheduled refresh (GitHub Actions)

`.github/workflows/refresh.yml` runs on a schedule, one job per store
(matrix, `fail-fast: false`), each with its own SQLite cache key.

- `workflow_dispatch` → optional **`store`** input runs a single store; **`dry_run`**
  computes without pushing.
- Secrets to create: see [docs/github_secrets.md](docs/github_secrets.md)
  (one URL + token pair per store).
- On a **public** repo, GitHub Actions minutes are free/unlimited, so the
  schedule can run daily at no cost.

A separate `secret-scan` workflow fails the build if any credential pattern is
committed — defense in depth alongside GitHub secret scanning + push protection.

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
```

## Tunables (in `config.yaml`)

| Setting | Value |
|---|---|
| Backfill window | 24 months |
| Scoring window | 50,000 most-recent orders (by id) |
| Cold-start | 60-day decay × weight 5, capped 25% of #1 |
| Sale boost | `1 + discount × 0.6`; top sale item pinned to slot 2 (≥5% off) |
| House-brand pin | slot 3 (index 2), one per collection |
| Seasonal | in-season ×1.5, off-season ×0.05 |
| Out-of-stock | ×0.0 (sorts to bottom) |
| FBT | ≤8 picks, min co-occurrence 10 |
| Data-safety floor | 200 usable orders |

## Notes

- GraphQL Admin API only (no REST). Assumes Shopify Plus rate limits.
- The house-brand selector matches a `custom.znacka` metafield value; `02b`
  aborts loudly if it resolves zero products (catches selector drift).
- Seasonal occasion maps are per-store (localized) in `config.yaml`.
