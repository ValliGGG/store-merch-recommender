/* ARTMiE — smart "Back to shop" button (v1)
 * On product pages, the back button has a Liquid-resolved fallback href
 * (in-context collection / metafield collection / first collection / /collections/all).
 * If the user navigated here from this same store, prefer history.back()
 * so scroll position and applied filters are preserved.
 *
 * Triggered ONLY on links tagged with data-artmie-back.
 * Safe by design: external/empty referrers fall through to the Liquid href.
 */
(function () {
  function sameOrigin(href) {
    try { return new URL(href, location.href).origin === location.origin; }
    catch (_) { return false; }
  }
  document.addEventListener("click", function (e) {
    var a = e.target && e.target.closest && e.target.closest("a[data-artmie-back]");
    if (!a) return;
    // Allow ctrl/cmd/middle-click to open in new tab as usual.
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button === 1) return;
    var ref = document.referrer;
    if (!ref || !sameOrigin(ref)) return;
    try {
      var refUrl = new URL(ref);
      // Avoid pointless self-loops if previous URL is the same product page.
      if (refUrl.pathname === location.pathname) return;
      // Avoid going back to /search results that immediately redirected here
      // (the search-redirect would just bounce us forward again).
      if (refUrl.pathname === "/search") return;
    } catch (_) { return; }
    if (history.length <= 1) return;
    e.preventDefault();
    history.back();
  }, true);
})();
