"""Configuration loader — store-parameterized.

config.yaml is structured as:
    defaults: { api_version, paths, backfill, scoring, fbt, seasonal, ... }
    stores:   { sk: {...}, cz: {...}, pl: {...}, ... }

`load(store)` deep-merges defaults <- stores[store] and resolves THAT store's
own SHOP_URL / TOKEN env vars.  Tokens are never mixed between stores: each
store entry names its own *_STORE_URL / *_API_TOKEN env vars and load() reads
only those.

- Env vars are loaded from the shared shopify-reports/.env (canonical token
  store) and then a local .env override.  On CI neither file exists; the
  values come straight from the job's `env:` block.
"""
from __future__ import annotations

import copy
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# stdlib has no YAML; do a minimal safe-load via PyYAML if present, else fail loud.
try:
    import yaml  # type: ignore
except ImportError:
    print("ERROR: PyYAML not installed.  Run:  pip install pyyaml", file=sys.stderr)
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "config.yaml"
# Shared token store path is overridable so the same code runs on any machine.
SHARED_ENV = Path(
    os.environ.get(
        "ARTMIE_SHARED_ENV",
        r"C:/Users/Valerian/Desktop/Claude 1TEST/shopify-reports/.env",
    )
)
LOCAL_ENV = PROJECT_ROOT / ".env"

DEFAULT_STORE = "sk"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


# Load env from shared first, then local override
_load_env_file(SHARED_ENV)
_load_env_file(LOCAL_ENV)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge `override` onto a deep copy of `base`."""
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


@dataclass
class ShopConfig:
    store_url: str
    api_token: str
    api_version: str

    @property
    def graphql_url(self) -> str:
        return f"https://{self.store_url}/admin/api/{self.api_version}/graphql.json"


@dataclass
class Config:
    raw: dict          # the merged (defaults <- store) config
    store: str         # store code, e.g. "sk"
    shop: ShopConfig
    db_path: Path
    log_dir: Path

    # ---- shared pipeline config (unchanged keys) --------------------------
    @property
    def backfill_months(self) -> int:
        return int(self.raw["backfill"]["months"])

    @property
    def scoring(self) -> dict:
        return self.raw["scoring"]

    @property
    def artmie_brand(self) -> dict:
        return self.raw["artmie_brand"]

    @property
    def fbt(self) -> dict:
        return self.raw["fbt"]

    @property
    def seasonal(self) -> dict:
        return self.raw["seasonal"]

    # ---- per-store knobs --------------------------------------------------
    @property
    def handle_filter(self) -> str | None:
        """Substring a handle must contain to be eligible (None = no filter)."""
        return self.raw.get("handle_filter")

    @property
    def mode(self) -> str:
        """'full' (score from own orders) or 'borrow' (use another store's signal)."""
        return (self.raw.get("mode") or "full").lower()

    @property
    def min_orders_floor(self) -> int:
        return int(self.raw.get("min_orders_floor", 0))

    @property
    def borrow_from(self) -> str | None:
        return self.raw.get("borrow_from")

    @property
    def borrow_key(self) -> str:
        return self.raw.get("borrow_key", "sku")

    @property
    def pilot_collection(self) -> str | None:
        return self.raw.get("pilot_collection")


def available_stores() -> list[str]:
    raw_all = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    return list((raw_all.get("stores") or {}).keys())


def load(store: str | None = None) -> Config:
    raw_all = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    defaults = raw_all.get("defaults") or {}
    stores = raw_all.get("stores") or {}

    store = (store or os.environ.get("ARTMIE_STORE") or DEFAULT_STORE).lower()
    if store not in stores:
        print(
            f"ERROR: unknown store {store!r}. Known stores: {', '.join(sorted(stores))}",
            file=sys.stderr,
        )
        sys.exit(2)

    merged = _deep_merge(defaults, stores[store])

    url_env = merged.get("store_url_env")
    tok_env = merged.get("api_token_env")
    if not url_env or not tok_env:
        print(f"ERROR: store {store!r} missing store_url_env / api_token_env", file=sys.stderr)
        sys.exit(2)
    store_url = os.environ.get(url_env)
    token = os.environ.get(tok_env)
    if not store_url or not token:
        print(f"ERROR: missing env {url_env} or {tok_env} for store {store!r}", file=sys.stderr)
        sys.exit(2)

    db_template = merged["paths"]["db"]
    db_path = (PROJECT_ROOT / db_template.format(store=store)).resolve()
    log_dir = (PROJECT_ROOT / merged["paths"]["logs"]).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    return Config(
        raw=merged,
        store=store,
        shop=ShopConfig(
            store_url=store_url,
            api_token=token,
            api_version=merged["api_version"],
        ),
        db_path=db_path,
        log_dir=log_dir,
    )
