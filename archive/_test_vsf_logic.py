"""Run the VSF JS logic in Python against the 3 actual product variant sets."""
import unicodedata
def normalize(s):
    if not s: return ""
    s = str(s).lower().strip()
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def variant_matches_all(v_opts, filter_values):
    combined = " ".join(normalize(o) for o in v_opts).strip()
    if not combined: return False
    return all(fv in combined for fv in filter_values)

def should_hide(variants, filter_values):
    if not variants: return False
    if len(variants) == 1:
        only = " ".join(normalize(o) for o in variants[0][:3])
        if not only or only.strip() == "default title": return False
    for v in variants:
        if variant_matches_all(v[:3], filter_values) and v[3] == 1:
            return False
    return True

# 3 products with their variants
products = {
    "FBCF64 (papier)": [
        ("Default Title","","",0),
        ("żółto brązowa","","",1), # in stock
        ("cytrynowa","","",1),
        ("ochrowa","","",0),
        ("jasno różowa","","",0),
        ("liliowa","","",1),
        ("królewski niebieski","","",1),
        ("wiosenna zielona","","",0),
        ("jasno zielona","","",0),
        ("ciemno zielona","","",1),
    ],
    "JOV506 (jovi)": [
        ("Default Title","","",0),
        ("Biały","","",0),("Żółta","","",0),("Pomarańczowa","","",0),
        ("Czerwona","","",0),("Różowa","","",0),
        ("odcień cielisty","","",0),("brązowy","","",0),
        ("Jasnozielony","","",1),("Ciemno zielona","","",0),
        ("Jasnoniebieski","","",0),
        ("fioletowy","","",0),  # purple OOS
        ("ciemnoniebieski","","",0),("Czarna","","",0),
    ],
    "CCH20 (bibula)": [
        ("Default Title","","",0),
        ("różowa","","",1),
        ("jasnofioletowa","","",1),  # PURPLE in stock
        ("żółta","","",0),
        ("szara","","",0),
        ("biel","","",1),
        ("czerwona","","",0),
        ("fioletowa","","",1),  # PURPLE in stock
        ("niebieska","","",0),
        ("zielona","","",0),
        ("czarna","","",1),
    ],
}

filter_values = [normalize("fioletowa")]
print(f"Filter: fioletowa  (normalized: '{filter_values[0]}')")
print()
for name, vars in products.items():
    hide = should_hide(vars, filter_values)
    expected = {"FBCF64 (papier)": True, "JOV506 (jovi)": True, "CCH20 (bibula)": False}[name]
    ok = "✓" if hide == expected else "✗"
    print(f"  {ok} {name}: hide={hide}  expected={expected}")
