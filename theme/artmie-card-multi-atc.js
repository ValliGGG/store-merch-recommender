/* ARTMiE — Multi-variant card add-to-cart redirect (v1)
 *
 * Problem: clicking the card's "DO KOSZYKA" button on a multi-variant
 * product silently adds whichever variant the theme chose (typically the
 * first available one). On products like "Tempera JOVI 500 ml — wybierz
 * odcień" with 14 colour variants, the customer who clicks ATC under a
 * "purple" filter ends up with a green paint in their cart.
 *
 * Fix: for products with more than one real variant (excluding the
 * placeholder "Default Title"), intercept the card ATC click and navigate
 * to the product page so the customer explicitly picks a variant.
 * Single-variant products keep their direct add-to-cart behaviour.
 *
 * Reads the same data-artmie-vsf attribute already emitted on every card.
 * Zero new network requests, ~1KB minified.
 */
(function () {
  "use strict";

  function realVariantCount(card) {
    var raw = card.getAttribute("data-artmie-vsf");
    if (!raw) return null;  // unknown — let default behavior happen
    var data;
    try { data = JSON.parse(raw); }
    catch (_) { return null; }
    var vars = data.v || [];
    var n = 0;
    for (var i = 0; i < vars.length; i++) {
      var v = vars[i];
      var combined = ((v[0] || "") + (v[1] || "") + (v[2] || "")).toLowerCase().trim();
      if (combined && combined !== "default title") n++;
    }
    return n;
  }

  document.addEventListener("click", function (e) {
    // Allow modifier-clicks (cmd/ctrl/middle) for new-tab behaviour.
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button === 1) return;
    var btn = e.target && e.target.closest && e.target.closest(".product-card-actions__button--cart");
    if (!btn) return;
    if (btn.disabled) return;
    var card = btn.closest("product-card");
    if (!card) return;
    var n = realVariantCount(card);
    if (n === null || n <= 1) return;  // single variant: allow direct ATC
    // Multi-variant: navigate to the PDP so the customer picks the variant.
    var link = card.querySelector("a.product-card__link, a.custom-pdp-section__back-button, a[href*='/products/']");
    var href = (link && link.getAttribute("href")) || "";
    if (!href) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    location.href = href;
  }, true);
})();
