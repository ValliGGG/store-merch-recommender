import os, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / 'scripts'))
from lib import config as cfg_mod
cfg_mod.load()
from urllib import request, parse

for code in ['SK','PL','BA','MK']:
    url = os.environ[f'ARTMIE_{code}_STORE_URL']
    tok = os.environ[f'ARTMIE_{code}_API_TOKEN']
    api = f'https://{url}/admin/api/2025-01'
    H = {'X-Shopify-Access-Token': tok}
    themes = json.loads(request.urlopen(request.Request(f'{api}/themes.json', headers=H)).read())['themes']
    main = next(t for t in themes if t['role'] == 'main')
    qs = parse.urlencode({'asset[key]': 'assets/artmie-cards.css'})
    body = json.loads(request.urlopen(request.Request(f'{api}/themes/{main["id"]}/assets.json?{qs}', headers=H)).read())
    val = body['asset']['value']
    print(f'[{code}] artmie-cards.css {len(val)} chars  marker={"ARTMIE_NO_DUP_ATC_v1" in val}  rule={".alternative-products .add-to-cart-button" in val}')
