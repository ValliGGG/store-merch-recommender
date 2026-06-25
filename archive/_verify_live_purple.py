"""End-to-end verification: fetch the user's URL, run the JS logic on the actual
data-artmie-vsf payloads in the served HTML, predict which products would be hidden."""
from urllib import request
import re, html as htmllib, json, unicodedata

def normalize(s):
    if not s: return ""
    s = str(s).lower().strip()
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def variant_matches_all(v_opts, fvs):
    combined = " ".join(normalize(o) for o in v_opts).strip()
    if not combined: return False
    return all(fv in combined for fv in fvs)

def should_hide(variants, filter_values):
    if not variants: return False
    if len(variants) == 1:
        only = " ".join(normalize(o) for o in variants[0][:3])
        if not only or only.strip() == "default title": return False
    for v in variants:
        if variant_matches_all(v[:3], filter_values) and v[3] == 1:
            return False
    return True

u = "https://artmie.pl/collections/papier-i-arkusze-rysunkowe?filter.p.m.custom.farba=fioletowa&filter.v.availability=1&sort_by=manual"
print(f"URL: {u}\n")
htm = request.urlopen(request.Request(u, headers={"User-Agent":"Mozilla/5.0"}), timeout=25).read().decode("utf-8","replace")

filter_values = []
from urllib.parse import urlparse, parse_qs
q = parse_qs(urlparse(u).query)
for k, vs in q.items():
    if k.startswith("filter.v.option.") or re.match(r"filter\.p\.m\.[^.]+\.[^.]+$", k):
        for v in vs:
            filter_values.append(normalize(v))
print(f"Extracted filter values: {filter_values}\n")

# Find each card with its handle and data
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
        h = should_hide(vars, filter_values)
        marker = "HIDE" if h else "show"
        if h: hidden += 1
        print(f"  {n}. [{marker}]  {handle[:60]}  ({len(vars)} variants)")
    except Exception as e:
        print(f"  {n}. ERR  {handle[:60]}  {e}")
print(f"\nTotal: {n} cards, predicted hidden: {hidden}")
