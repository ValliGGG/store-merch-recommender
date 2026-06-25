"""Try the actual section_id and see if it returns cards with data-artmie-vsf."""
from urllib import request
import re

sec_ids = ['template--20567507534068__main',
           'sections--20567507960052__header_section',
           'template--20567507534068__artmie_col_desc',
           'template--20567507534068__artmie_col_nav']

for sid in sec_ids:
    u = f"https://artmie.pl/collections/papier-i-arkusze-rysunkowe?filter.p.m.custom.farba=fioletowa&filter.v.availability=1&section_id={sid}"
    print(f"\n=== sid={sid}")
    try:
        h = request.urlopen(request.Request(u, headers={"User-Agent":"Mozilla/5.0"}), timeout=15).read().decode("utf-8","replace")
    except Exception as e:
        print(f"   FAIL {e}"); continue
    n_cards = len(re.findall(r'<product-card\b', h))
    n_vsf = len(re.findall(r'data-artmie-vsf="', h))
    print(f"   length: {len(h):>7}  cards: {n_cards}  vsf attrs: {n_vsf}")
    if n_cards > 0 and n_vsf == 0:
        # Show a sample card
        sample = re.search(r'<product-card[^>]*>', h)
        if sample:
            print(f"   sample: {sample.group(0)[:300]}")
