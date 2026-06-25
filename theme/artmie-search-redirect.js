/* ARTMiE Search Redirect — intercepts /search?q=X and redirects to a sorted
 * category collection when the query matches a known term.
 *
 * Why: Shopify URL redirects don't fire for /search paths (the search controller
 * intercepts first). For category-like queries we want the customer to land on
 * the manually-sorted collection page (best-sellers + sale-pin + Artmie-pin +
 * OOS-bottom) instead of a relevance-ranked list with OOS items at the top.
 *
 * Loaded on every page; no-ops outside /search. Total payload < 2KB.
 *
 * Per-locale dictionary detected by hostname (artmie.sk / artmie.pl / artmie.ba / artmie.mk).
 * Update the dictionaries below to add new redirects.
 */
(function () {
  'use strict';
  if (!window.location.pathname.startsWith('/search')) return;

  var params = new URLSearchParams(window.location.search);
  var q = (params.get('q') || '').trim().toLowerCase();
  if (!q) return;

  var fold = function (s) {
    return s.toLowerCase()
      .normalize('NFD').replace(/[̀-ͯ]/g, '')   // strip diacritics
      .replace(/\s+/g, ' ').trim();
  };
  var qFolded = fold(q);

  // Per-host dictionaries: { foldedQuery: '/collections/handle' }
  var DICTIONARIES = {
    'artmie.sk': {
      'akrylove farby': '/collections/umelecke-farby',
      'akrylova farba': '/collections/umelecke-farby',
      'akryl': '/collections/umelecke-farby',
      'olejove farby': '/collections/umelecke-farby',
      'olejova farba': '/collections/umelecke-farby',
      'olej': '/collections/umelecke-farby',
      'akvarel': '/collections/umelecke-farby',
      'akvarelove farby': '/collections/umelecke-farby',
      'vodove farby': '/collections/umelecke-farby',
      'acrylic': '/collections/umelecke-farby',
      'acrylic paint': '/collections/umelecke-farby',
      'acrylic paints': '/collections/umelecke-farby',
      'oil paint': '/collections/umelecke-farby',
      'watercolor': '/collections/umelecke-farby',
      'stetce': '/collections/umelecke-stetce-a-pomocky',
      'stetec': '/collections/umelecke-stetce-a-pomocky',
      'brush': '/collections/umelecke-stetce-a-pomocky',
      'brushes': '/collections/umelecke-stetce-a-pomocky',
      'platno': '/collections/maliarske-platna',
      'maliarske platno': '/collections/maliarske-platna',
      'canvas': '/collections/maliarske-platna',
      'papier': '/collections/papier-scrapbook-dekupaz',
      'paper': '/collections/papier-scrapbook-dekupaz',
      'pastely': '/collections/pastely-a-fixy',
      'pastel': '/collections/pastely-a-fixy',
      'ceruzky': '/collections/ceruzky-a-grafika',
      'ceruzka': '/collections/ceruzky-a-grafika',
      'pencil': '/collections/ceruzky-a-grafika',
      'scrapbook': '/collections/scrapbooking',
      'dekupaz': '/collections/dekupaz-servitkovanie',
      'modelovanie': '/collections/modelovanie-a-odlievanie',
      'vianoce': '/collections/vianoce',
      'vianocny': '/collections/vianoce',
      'christmas': '/collections/vianoce',
      'valentin': '/collections/valentin',
      'svadba': '/collections/svadba',
      'artmie': '/collections/artmie-r'
    },
    'artmie.pl': {
      'farby akrylowe': '/collections/farby-artystyczne',
      'akryl': '/collections/farby-artystyczne',
      'farby olejne': '/collections/farby-artystyczne',
      'olej': '/collections/farby-artystyczne',
      'akwarele': '/collections/farby-artystyczne',
      'akwarela': '/collections/farby-artystyczne',
      'acrylic': '/collections/farby-artystyczne',
      'watercolor': '/collections/farby-artystyczne',
      'pedzle': '/collections/pedzle-artystyczne-i-akcesoria',
      'pedzel': '/collections/pedzle-artystyczne-i-akcesoria',
      'brush': '/collections/pedzle-artystyczne-i-akcesoria',
      'plotno': '/collections/podobrazia-malarskie',
      'podobrazia': '/collections/podobrazia-malarskie',
      'canvas': '/collections/podobrazia-malarskie',
      'papier': '/collections/papier-i-arkusze-rysunkowe',
      'paper': '/collections/papier-i-arkusze-rysunkowe',
      'pastele': '/collections/pastele-i-markery',
      'olowki': '/collections/olowki-i-grafika',
      'olowek': '/collections/olowki-i-grafika',
      'pencil': '/collections/olowki-i-grafika',
      'scrapbooking': '/collections/scrapbooking',
      'decoupage': '/collections/scrapbooking',
      'modelowanie': '/collections/modelowanie',
      'swieta': '/collections/dekoracje-sezonowe',
      'christmas': '/collections/dekoracje-sezonowe',
      'walentynki': '/collections/dekoracje-sezonowe'
    },
    'artmie.ba': {
      'akrilne boje': '/collections/umjetnicke-boje',
      'akril': '/collections/umjetnicke-boje',
      'uljane boje': '/collections/umjetnicke-boje',
      'akvarelne boje': '/collections/umjetnicke-boje',
      'akvarel': '/collections/umjetnicke-boje',
      'acrylic': '/collections/umjetnicke-boje',
      'kistovi': '/collections/umjetnicki-kistovi-i-pribor',
      'kist': '/collections/umjetnicki-kistovi-i-pribor',
      'brush': '/collections/umjetnicki-kistovi-i-pribor',
      'platno': '/collections/slikarska-platna',
      'platna': '/collections/slikarska-platna',
      'canvas': '/collections/slikarska-platna',
      'papir': '/collections/papir-scrapbook-dekupaz',
      'paper': '/collections/papir-scrapbook-dekupaz',
      'pasteli': '/collections/pasteli-i-flomasteri',
      'olovke': '/collections/olovke-i-grafika',
      'olovka': '/collections/olovke-i-grafika',
      'modeliranje': '/collections/modeliranje-i-odlijevanje',
      'bozic': '/collections/sezonsko-stvaralastvo',
      'christmas': '/collections/sezonsko-stvaralastvo'
    },
    'artmie.mk': {
      'akrilni boi': '/collections/umetnicki-boi',
      'masleni boi': '/collections/umetnicki-boi',
      'akvareli': '/collections/umetnicki-boi',
      'acrylic': '/collections/umetnicki-boi',
      'cetki': '/collections/umetnicki-cetki-i-pribor',
      'brush': '/collections/umetnicki-cetki-i-pribor',
      'platna': '/collections/slikarski-platna',
      'canvas': '/collections/slikarski-platna',
      'hartija': '/collections/hartija-skrapbuk-decoupage',
      'paper': '/collections/hartija-skrapbuk-decoupage',
      'bozic': '/collections/sezonska-izrada',
      'christmas': '/collections/sezonska-izrada'
    }
  };

  // Pick dictionary by hostname suffix
  var host = (window.location.hostname || '').toLowerCase();
  var dict = null;
  for (var key in DICTIONARIES) {
    if (host.indexOf(key) !== -1) { dict = DICTIONARIES[key]; break; }
  }
  if (!dict) return;

  var target = dict[qFolded];
  if (!target) return;

  // Replace (not push) so the back button doesn't loop user into a redirect
  window.location.replace(target);
})();
