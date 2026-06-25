"""Replay the user's URL with v3 OR-within-filter logic."""
from urllib import request, parse
import re, html as htmllib, json, unicodedata

def normalize(s):
    if not s: return ""
    s = str(s).lower().strip()
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def variant_satisfies(v_opts, filters):
    combined = " ".join(normalize(o) for o in v_opts).strip()
    if not combined: return False
    for k, vals in filters.items():
        if not any(vv in combined for vv in vals):
            return False
    return True

def should_hide(variants, filters):
    if not variants: return False
    if len(variants) == 1:
        only = " ".join(normalize(o) for o in variants[0][:3])
        if not only or only.strip() == "default title": return False
    for v in variants:
        if variant_satisfies(v[:3], filters) and v[3] == 1:
            return False
    return True

u = "https://artmie.pl/collections/papier-i-arkusze-rysunkowe?filter.p.m.custom.farba=fioletowa&filter.p.m.custom.farba=bronzov%C3%A1&filter.v.availability=1&sort_by=manual"
print(f"URL: {u}\n")

# Parse filters as dict-of-lists (OR within key)
filters = {}
q = parse.parse_qs(parse.urlparse(u).query)
for k, vs in q.items():
    if k.startswith("filter.v.option.") or re.match(r"filter\.p\.m\.[^.]+\.[^.]+$", k):
        filters[k] = [normalize(v) for v in vs]
print(f"Filter dict: {filters}\n")

htm = request.urlopen(request.Request(u, headers={"User-Agent":"Mozilla/5.0"}), timeout=25).read().decode("utf-8","replace")
matches = re.finditer(r'<product-card[^>]*data-artmie-vsf="([^"]*)"[^>]*>(.*?)</product-card>', htm, re.DOTALL)
n = 0
hidden = 0
for m in matches:
    n += 1
    raw = htmllib.unescape(m.group(1))
    body = m.group(2)
    handle_m = re.search(r'/products/([a-z0-9\-]+)', body)
    handle = handle_m.group(1) if handle_m else "?"
    try:
        data = json.loads(raw)
        vars = data.get("v", [])
        h = should_hide(vars, filters)
        # Multi-variant flag
        real = sum(1 for v in vars if (str(v[0])+str(v[1])+str(v[2])).lower().strip() not in ("","default title"))
        atc_redirect = real > 1
        marker = "HIDE" if h else "show"
        atc = "→PDP" if atc_redirect else "ATC↓"
        if h: hidden += 1
        # Show which variants matched (for debugging)
        matched = [v[:3] for v in vars if variant_satisfies(v[:3], filters) and v[3]==1]
        print(f"  {n}. [{marker}] [{atc}]  {handle[:55]:55s}  variants={len(vars)}  matched_in_stock={matched}")
    except Exception as e:
        print(f"  {n}. ERR  {handle[:55]}  {e}")
print(f"\nTotal: {n} cards, hidden: {hidden}")
