# Homepage bestsellers per category — setup

**Goal:** Show the top sellers from various art-supply categories on the SK
homepage, in a "Featured collection per tile" pattern.

**Approach:** Use the existing curated category collections (no new collections
needed). 03b sorts every collection by best-seller score with sale + Artmie
pins applied — the homepage tiles will reflect that ranking automatically.

**Performance:** Each tile renders products from a Shopify collection
server-side. Same render path as today's `product_list` section. **Zero perf
impact.** No new theme JS, no new HTTP requests.

---

## Current homepage state (Horizon theme, SK locale)

`templates/index.json` has 5 sections:

1. `section_HfYMnx` — hero
2. `artmie_cat_grid_2025` — custom Artmie categories grid
3. `product_list_fa6P9H` — Shopify product list (currently shows collection `all`)
4. `artmie_homepage_seo` — custom SEO copy block
5. `signup_form_GVrqVK` — signup form

Section 3 is the only data-driven product showcase. To add per-category
bestsellers, we add more `product-list` sections (one per category), each
pointing to a category collection.

---

## Recommended homepage tiles (in order)

Pick **6 tiles** for above-the-fold + just-below-fold visibility. Each tile is
a Shopify "Featured collection" / "Product list" section pointing to one of
the existing collections below.

| # | Section title (display) | Collection handle | Products | Why |
|---|---|---|---|---|
| 1 | **Bestsellery** | `bestsellery` | 94 | Cross-category bestsellers — strongest top-10 picks store-wide |
| 2 | **Umelecké farby** (Art paints) | `umelecke-farby` | 796 | Largest art-supply category by revenue |
| 3 | **Umelecké štetce a pomôcky** (Art brushes & tools) | `umelecke-stetce-a-pomocky` | 1,038 | High-frequency repeat purchase |
| 4 | **Papier, scrapbook a dekupáž** (Paper, scrapbook, decoupage) | `papier-scrapbook-dekupaz` | 1,421 | Big creative category, gift-giving driver |
| 5 | **Kreatívne potreby pre deti** (Kids creative supplies) | `kreativne-potreby-pre-deti` | 1,452 | Family / parent buyer segment |
| 6 | **Sezónne tvorenie** (Seasonal making) | `sezonne-tvorenie` | 737 | Auto-rotates with season (off-season products are tagged `hidden:off-season` → hidden by 03b filter) |

Recommended display: **6–8 products per tile** (matches FBT count, fills a
typical 4-up or 6-up grid without over-promoting).

Show "View all" link per tile (Horizon supports this natively in the
`product-list` section settings).

---

## How to wire it (theme editor steps)

This is a manual step in the Shopify admin theme editor — it's auto-saving
to `templates/index.json` so I can't safely script it without risking
overwrite by future admin edits.

1. Online Store → Themes → Horizon (Live) → **Customize**
2. On the home page template, find the existing `product_list_fa6P9H` section.
   You can either:
   - **Repurpose it:** change its collection from `all` to `bestsellery`
   - **Or duplicate it 5 more times** for the other tiles
3. For each `product-list` section:
   - **Collection:** pick one from the table above
   - **Products to show:** 6 or 8
   - **Heading:** the display title from the table
   - **Show "View all" link:** ON
   - **Sort:** leave as collection default (this is the one we set via 03b — `MANUAL`)
4. Drag tiles into desired order around the existing
   `artmie_cat_grid_2025`, `artmie_homepage_seo`, signup form
5. Save

---

## What about other locales?

If you also want this on PL/BA/MK homepages, the same approach works — those
stores already have their own Horizon templates (see memory note about
`templates/index.context.{market}.json`). But this scope is SK-only per the
spec. Re-running the same 03b script against PL/BA/MK stores (with their
respective tokens) would sort their collections too, ready for homepage
wiring.

---

## Refresh cadence

The collections re-sort weekly (Sunday 03:00 Bratislava) via
`ops/weekly_refresh.bat`. Homepage tiles automatically reflect the new sort
because they read from the live collection — no theme deploy required.

If you launch a flash sale and want the homepage to reflect it within hours
(not the next Sunday), trigger `scripts/03b_compute_bestsellers.py`
manually after the sale starts.
