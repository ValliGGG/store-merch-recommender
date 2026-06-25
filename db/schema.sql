-- ARTMiE Recommender — SQLite schema
-- Tables are idempotent (CREATE IF NOT EXISTS) so the file can be re-applied.

CREATE TABLE IF NOT EXISTS orders (
  id            TEXT PRIMARY KEY,
  created_at    TEXT NOT NULL,
  customer_id   TEXT,
  cancelled_at  TEXT,
  financial_status TEXT
);

CREATE TABLE IF NOT EXISTS line_items (
  id                TEXT PRIMARY KEY,
  order_id          TEXT NOT NULL,
  product_id        TEXT NOT NULL,
  product_legacy_id INTEGER,
  variant_id        TEXT,
  quantity          INTEGER NOT NULL,
  refunded_quantity INTEGER NOT NULL DEFAULT 0,
  unit_price        REAL,
  currency          TEXT
);

-- Cached product metadata, refreshed on every run by 02b_refresh_products.py
CREATE TABLE IF NOT EXISTS products (
  id              TEXT PRIMARY KEY,
  legacy_id       INTEGER,
  handle          TEXT,
  title           TEXT,
  vendor          TEXT,
  brand           TEXT,            -- resolved Artmie/3rd-party brand value (NOT vendor)
  is_artmie       INTEGER NOT NULL DEFAULT 0,  -- 1 if brand resolves to Artmie
  product_type    TEXT,
  tags            TEXT,            -- comma-joined tags
  status          TEXT,            -- ACTIVE / DRAFT / ARCHIVED
  total_inventory INTEGER,
  created_at      TEXT,
  updated_at      TEXT,
  occasion_tags   TEXT,            -- comma-joined values from custom.prilezitost
  season_tags     TEXT,            -- mapped season:* tags (computed)
  price_min       REAL,            -- cheapest variant price
  compare_at_max  REAL,            -- largest variant compare-at price
  discount_pct    REAL NOT NULL DEFAULT 0  -- (compare_at_max - price_min) / compare_at_max, 0 if not on sale
);

-- Track which season tags we wrote, so weekly refresh can clean them up
CREATE TABLE IF NOT EXISTS managed_tags (
  product_id TEXT NOT NULL,
  tag        TEXT NOT NULL,
  applied_at TEXT NOT NULL,
  PRIMARY KEY (product_id, tag)
);

-- Run history for incremental sync
CREATE TABLE IF NOT EXISTS sync_runs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  kind        TEXT NOT NULL,       -- 'initial' | 'incremental' | 'products' | 'sort' | 'fbt' | 'mask'
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  status      TEXT NOT NULL,       -- 'running' | 'ok' | 'failed'
  notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_lineitems_order   ON line_items(order_id);
CREATE INDEX IF NOT EXISTS idx_lineitems_product ON line_items(product_id);
CREATE INDEX IF NOT EXISTS idx_orders_created    ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_cancelled  ON orders(cancelled_at);
CREATE INDEX IF NOT EXISTS idx_products_brand    ON products(is_artmie);
CREATE INDEX IF NOT EXISTS idx_products_status   ON products(status);
