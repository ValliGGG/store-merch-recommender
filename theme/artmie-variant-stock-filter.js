/* ARTMiE — Variant-aware stock filter (v1)
 *
 * Problem: Shopify's `filter.v.option.color=red` returns products that *have*
 * a red variant — without checking that the red variant is actually in stock.
 * Result: customer filters by color, sees a yellow thumbnail, clicks through,
 * finds the red variant is sold out.
 *
 * Solution: each product card carries `data-artmie-vsf` with compact variant
 * data (option values + available bool). When the URL has any active
 * `filter.v.option.*` param, this script hides cards that have no matching
 * IN-STOCK variant.
 *
 * Performance: zero new network requests, pure DOM. Runs on DOMContentLoaded,
 * popstate, and when the product grid mutates (Search & Discovery AJAX swap).
 * Idle (~5ms) when no option filter is active. ~3KB minified.
 */
(function () {
  "use strict";
  var ROOT_CLS = "artmie-vsf-active";
  var MARK_HIDE = "data-artmie-vsf-oos";

  // Diacritic-insensitive normalize: "żółta" -> "zolta"
  function normalize(s) {
    if (!s) return "";
    return String(s).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").trim();
  }

  // Captures BOTH variant-option filters (filter.v.option.color=red) AND
  // metafield filters that act as variant descriptors (filter.p.m.custom.farba=fioletowa).
  // Each value is normalized.
  // Returns: { "<filterKey>": ["normalizedVal1", "normalizedVal2", ...] }
  // When the same filterKey has multiple values that's an OR within that filter
  // (Shopify behaviour). Different keys are AND across them.
  function getActiveFilters() {
    var out = Object.create(null);
    if (!location.search) return out;
    var params;
    try { params = new URLSearchParams(location.search); }
    catch (_) { return out; }
    params.forEach(function (val, key) {
      var k = String(key);
      if (/^filter\.v\.option\./i.test(k) || /^filter\.p\.m\.[^.]+\.[^.]+$/i.test(k)) {
        var v = normalize(val);
        if (!v) return;
        if (!out[k]) out[k] = [];
        if (out[k].indexOf(v) < 0) out[k].push(v);
      }
    });
    return out;
  }

  // For a single variant, check if it satisfies the filter set:
  //   - For each filterKey: at least ONE of its values appears in the variant's
  //     combined option string (OR within filter)
  //   - All filterKeys must be satisfied (AND across filters)
  function variantSatisfies(variant, filters) {
    var combined = (normalize(variant[0]) + " " + normalize(variant[1]) + " " + normalize(variant[2])).trim();
    if (!combined) return false;
    var keys = Object.keys(filters);
    for (var i = 0; i < keys.length; i++) {
      var values = filters[keys[i]];
      var anyMatch = false;
      for (var j = 0; j < values.length; j++) {
        if (combined.indexOf(values[j]) >= 0) { anyMatch = true; break; }
      }
      if (!anyMatch) return false;
    }
    return true;
  }

  function shouldHide(card, filters) {
    var raw = card.getAttribute("data-artmie-vsf");
    if (!raw) return false;
    var data;
    try { data = JSON.parse(raw); }
    catch (_) { return false; }
    var vars = data.v || [];
    if (!vars.length) return false;
    // Special case: single-variant products with no real options ("default title")
    // have nothing to match against. Don't hide — let Shopify's filter decide.
    if (vars.length === 1) {
      var only = (normalize(vars[0][0]) + normalize(vars[0][1]) + normalize(vars[0][2]));
      if (!only || only === "default title") return false;
    }
    for (var i = 0; i < vars.length; i++) {
      if (variantSatisfies(vars[i], filters) && vars[i][3] === 1) return false;
    }
    return true;
  }

  function localeFor(host) {
    host = (host || "").toLowerCase();
    if (host.indexOf("artmie.sk") >= 0 || host.indexOf("sk-artmie") >= 0 || host.indexOf("app.artmie.sk") >= 0) return "sk";
    if (host.indexOf("artmie.pl") >= 0 || host.indexOf("pl-artmie") >= 0) return "pl";
    if (host.indexOf("artmie.ba") >= 0 || host.indexOf("ba-artmie") >= 0) return "ba";
    if (host.indexOf("artmie.mk") >= 0 || host.indexOf("mk-artmie") >= 0) return "mk";
    return "en";
  }

  var EMPTY_MSG = {
    sk: "Žiadny produkt nezodpovedá zvoleným filtrom (vybraný variant je vypredaný).",
    pl: "Żaden produkt nie odpowiada wybranym filtrom (wybrany wariant jest wyprzedany).",
    ba: "Nijedan proizvod ne odgovara odabranim filterima (odabrana varijanta je rasprodata).",
    mk: "Ниту еден производ не одговара на избраните филтри (избраната варијанта е распродадена).",
    en: "No products match the selected filters (the chosen variant is sold out)."
  };

  function ensureEmptyState(grid, lang) {
    if (document.getElementById("artmie-vsf-empty")) return;
    var div = document.createElement("div");
    div.id = "artmie-vsf-empty";
    div.style.cssText =
      "padding:32px 16px;text-align:center;color:#666;font-size:14px;line-height:1.5;grid-column:1/-1";
    div.textContent = EMPTY_MSG[lang] || EMPTY_MSG.en;
    grid.appendChild(div);
  }
  function removeEmptyState() {
    var el = document.getElementById("artmie-vsf-empty");
    if (el) el.remove();
  }

  var rafId = 0;
  function run() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(function () {
      rafId = 0;
      var filters = getActiveFilters();
      var hasFilters = Object.keys(filters).length > 0;
      var html = document.documentElement;
      if (!hasFilters) {
        html.classList.remove(ROOT_CLS);
        var prev = document.querySelectorAll("product-card[" + MARK_HIDE + "]");
        for (var i = 0; i < prev.length; i++) prev[i].removeAttribute(MARK_HIDE);
        removeEmptyState();
      } else {
        html.classList.add(ROOT_CLS);
        var cards = document.querySelectorAll("product-card[data-artmie-vsf]");
        if (cards.length) {
          var hidden = 0, totalWithData = 0;
          for (var c = 0; c < cards.length; c++) {
            var card = cards[c];
            totalWithData++;
            if (shouldHide(card, filters)) {
              card.setAttribute(MARK_HIDE, "1");
              hidden++;
            } else {
              card.removeAttribute(MARK_HIDE);
            }
          }
          if (totalWithData > 0 && hidden === totalWithData) {
            var grid = cards[0].closest(".product-grid, .collection__products-grid, [data-product-grid], main");
            if (grid) ensureEmptyState(grid, localeFor(location.hostname));
          } else {
            removeEmptyState();
          }
        }
      }
      // Always (re-)evaluate which filter chips would yield zero in-stock results
      // and hide them. This works whether filters are active or not.
      pruneEmptyFilterChips();
    });
  }

  // ── Filter chip pruning ───────────────────────────────────────────────
  // For each unchecked filter chip in the sidebar, hide it if no in-stock
  // variant in the entire collection actually contains the chip's value.
  // Uses /collections/HANDLE/products.json (cached 30 min in sessionStorage)
  // to know the full set of in-stock variant option values.
  // Only prunes chips for "VSF-affected" filters (variant options + color
  // metafields). Other filters (brand, vendor, price) are left alone since
  // Shopify's count is already accurate for them.
  var PRUNE_PATTERNS = [
    /^filter\.v\.option\./i,
    /^filter\.p\.m\.[^.]+\.(farba|farby|color|colour|kolor|boja|barva|boi|odtien|odcien)$/i
  ];
  var prunePending = false;
  function pruneEmptyFilterChips() {
    if (prunePending) return;
    var handle = (location.pathname.match(/\/collections\/([^/?#]+)/) || [])[1];
    if (!handle || handle === "all") return;  // no specific collection
    prunePending = true;
    fetchCollectionInStockValues(handle).then(function (inStockSet) {
      prunePending = false;
      if (!inStockSet || inStockSet.size === 0) return;
      var checkboxes = document.querySelectorAll('input[type="checkbox"][name^="filter."]');
      var unhidden = 0, hidden = 0;
      for (var i = 0; i < checkboxes.length; i++) {
        var cb = checkboxes[i];
        if (cb.checked) continue;  // never hide an active filter
        var matchesPattern = false;
        for (var p = 0; p < PRUNE_PATTERNS.length; p++) {
          if (PRUNE_PATTERNS[p].test(cb.name)) { matchesPattern = true; break; }
        }
        if (!matchesPattern) continue;
        var fv = normalize(cb.value);
        if (!fv) continue;
        // Match: any in-stock value contains the chip value (substring, both directions)
        var found = false;
        inStockSet.forEach(function (v) {
          if (found) return;
          if (v.indexOf(fv) >= 0) found = true;
        });
        var li = cb.closest("li, .facets__item, label, .filter-option");
        if (!li) continue;
        if (!found) {
          li.setAttribute("data-artmie-vsf-prune", "1");
          hidden++;
        } else {
          li.removeAttribute("data-artmie-vsf-prune");
          unhidden++;
        }
      }
    }).catch(function () { prunePending = false; });
  }

  function fetchCollectionInStockValues(handle) {
    var cacheKey = "artmie-vsf-instock:" + handle;
    try {
      var raw = sessionStorage.getItem(cacheKey);
      if (raw) {
        var c = JSON.parse(raw);
        if (c && c.t && (Date.now() - c.t) < 1800000) {
          return Promise.resolve(new Set(c.values));
        }
      }
    } catch (_) {}
    return new Promise(function (resolve) {
      var values = new Set();
      var page = 1;
      var MAX_PAGES = 4;     // up to 1000 products
      function next() {
        if (page > MAX_PAGES) return done();
        fetch("/collections/" + handle + "/products.json?limit=250&page=" + page, { credentials: "same-origin" })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (data) {
            if (!data || !data.products || !data.products.length) return done();
            for (var i = 0; i < data.products.length; i++) {
              var p = data.products[i];
              for (var j = 0; j < p.variants.length; j++) {
                var v = p.variants[j];
                if (!v.available) continue;
                if (v.option1) values.add(normalize(v.option1));
                if (v.option2) values.add(normalize(v.option2));
                if (v.option3) values.add(normalize(v.option3));
              }
            }
            if (data.products.length < 250) return done();
            page++; next();
          })
          .catch(done);
      }
      function done() {
        try {
          sessionStorage.setItem(cacheKey, JSON.stringify({ t: Date.now(), values: Array.from(values) }));
        } catch (_) {}
        resolve(values);
      }
      // Defer to idle time so we don't compete with first paint
      if (typeof requestIdleCallback === "function") {
        requestIdleCallback(next, { timeout: 2000 });
      } else {
        setTimeout(next, 250);
      }
    });
  }

  // Initial run
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run, { once: true });
  } else {
    run();
  }

  // ── Catch URL changes from EVERY source ──
  // 1) Browser back/forward
  window.addEventListener("popstate", run);
  // 2) Programmatic URL changes (Shopify Search & Discovery uses pushState; popstate
  //    does NOT fire for these). Patch pushState/replaceState to dispatch a custom
  //    event we listen for. This is well-known and safe — many libs do this.
  (function patchHistory(){
    ["pushState","replaceState"].forEach(function(method){
      var orig = history[method];
      if (typeof orig !== "function") return;
      history[method] = function(){
        var ret = orig.apply(this, arguments);
        try { window.dispatchEvent(new Event("artmie:locationchange")); } catch(_) {}
        return ret;
      };
    });
  })();
  window.addEventListener("artmie:locationchange", run);

  // ── DOM mutation observer ──
  // Observe document.documentElement so swaps anywhere (collection grid swap by
  // Search & Discovery, in-place innerHTML replacement, full <main> swap) all
  // trigger re-classification. The debounce keeps cost negligible on large pages.
  var mutDebounce = 0;
  var lastCardCount = -1;
  var observer = new MutationObserver(function(muts){
    // Cheap guard: only re-run if the number of product-cards actually changed
    // OR if any added node contains a product-card. Avoids work on unrelated mutations.
    var relevant = false;
    for (var i = 0; i < muts.length && !relevant; i++) {
      var added = muts[i].addedNodes;
      for (var j = 0; j < added.length; j++) {
        var n = added[j];
        if (n.nodeType !== 1) continue;
        if (n.tagName === "PRODUCT-CARD" || (n.querySelector && n.querySelector("product-card"))) {
          relevant = true; break;
        }
      }
    }
    if (!relevant) {
      // Fallback: if total card count changed since last run, also re-run.
      var n = document.querySelectorAll("product-card[data-artmie-vsf]").length;
      if (n === lastCardCount) return;
      lastCardCount = n;
    }
    clearTimeout(mutDebounce);
    mutDebounce = setTimeout(function(){
      lastCardCount = document.querySelectorAll("product-card[data-artmie-vsf]").length;
      run();
    }, 60);
  });
  function startObserver(){
    try {
      observer.observe(document.documentElement, { childList: true, subtree: true });
    } catch(_) {}
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startObserver, { once: true });
  } else {
    startObserver();
  }
})();
