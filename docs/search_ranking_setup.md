# Search ranking — Search & Discovery app config

**Goal:** When a customer searches "akrylové farby" (or any term), the results should be:
1. ARTMiE-branded products first (matching the search term)
2. Then other brands, sorted by units sold

**Why this approach:** Shopify's native search ranking is opaque, but the free
**Search & Discovery** app (made by Shopify) lets you configure boost rules and
synonyms server-side. **No theme change, no client-side JS, no perf impact.**

For absolute control over ordering you'd need a custom Storefront API search
endpoint, but that adds latency and infra — start with Search & Discovery and
escalate only if results are unsatisfactory.

---

## One-time setup

### 1. Install Search & Discovery
- Admin → Apps → Shopify App Store → search "Search & Discovery" → Install
- Free, made by Shopify, server-side ranking

### 2. Configure synonyms (optional but recommended)
In the app, add common SK search synonyms so typos and language variants resolve correctly:

| Synonym group |
|---|
| `akryl, akrylové, acryl, acrylic, akrilové` |
| `plátno, platno, canvas, plotno` |
| `štetec, stetec, brush, štetce, stetce, pędzel` |
| `farba, farby, farb, paint, paints` |
| `vianoce, vianočný, christmas, xmas` |

Add more based on your top search query data (Admin → Analytics → Search reports).

### 3. Configure boosting rules

Search & Discovery → **Boost** rules. Add these in priority order:

| Priority | Rule | Effect |
|---|---|---|
| 1 | Boost products where `metafield: custom.znacka` equals `ARTMiE®` | ARTMiE-branded products surface first |
| 2 | Boost products where `metafield: custom.znacka` equals `ARTMiE` | Variant casing |
| 3 | Boost products in collection `bestsellery` | Top sellers get a lift |
| 4 | Demote products with tag `hidden:off-season` | Off-season items deprioritized in search |

**Important:** Boost rules don't override relevance scoring entirely — they
nudge results. A product must still be a relevant text match to surface for
a query. So "Boost ARTMiE" applied to query "akrylové farby" surfaces ARTMiE
acrylic paints first, not all ARTMiE products.

### 4. Default sort
- Search results page sort default: **Best selling** (which now uses our
  manual order from `03b_compute_bestsellers.py`).

---

## Verification (after setup)

After config:
- Search "akrylové farby" → first 3 results should include at least one ARTMiE
  acrylic paint
- Search "vianočný" in July → no Christmas products (off-season tag demotes them)
- Search "stetec" → ARTMiE brushes first, then top-selling third-party brushes

---

## What this does NOT cover

- **Filter ordering on search results** — separate concern, handled by
  `artmie-filters-accordion.js` (already deployed across SK/PL/BA/MK).
- **Search autocomplete suggestions** — Search & Discovery suggests products,
  not collections. If you want collection suggestions, a small theme tweak
  would be needed.
- **Per-customer personalization** — would require Shopify Plus's Audiences
  feature or a custom recommendation engine on top.

---

## When to escalate to custom search

If after a month of running with these rules:
- ARTMiE products don't reliably surface in top 3 for category queries, OR
- Search-conversion rate doesn't improve

…then consider Storefront API custom search. That's a 1–2 week build (custom
Algolia/Meilisearch index + theme integration) and IS a perf concern. Start
small and only escalate if needed.
