"""Minimal Shopify Admin GraphQL client with Plus rate limit awareness.

Plus stores: 2000 cost/sec restore, 20,000 bucket. We track the throttle status
returned with every response and back off proactively if the bucket gets thin.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error as urlerr
from urllib import request as urlreq

from .config import ShopConfig


@dataclass
class Throttle:
    available: float = 20000.0
    maximum:   float = 20000.0
    restore:   float = 2000.0


class ShopifyClient:
    def __init__(self, shop: ShopConfig, *, log=print):
        self.shop = shop
        self.log = log
        self.throttle = Throttle()

    # ---- low-level POST -----------------------------------------------------
    def _post(self, body: dict, timeout: int = 120) -> dict:
        data = json.dumps(body).encode("utf-8")
        req = urlreq.Request(
            self.shop.graphql_url,
            data=data,
            method="POST",
            headers={
                "X-Shopify-Access-Token": self.shop.api_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        last = None
        for attempt in range(5):
            try:
                with urlreq.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read())
            except urlerr.HTTPError as e:
                last = e
                if e.code in (429, 502, 503, 504):
                    wait = 2 ** attempt
                    self.log(f"  [retry] HTTP {e.code} -> sleeping {wait}s")
                    time.sleep(wait)
                    continue
                raise
            except urlerr.URLError as e:
                last = e
                wait = 2 ** attempt
                self.log(f"  [retry] URLError {e} -> sleeping {wait}s")
                time.sleep(wait)
        raise RuntimeError(f"Shopify request failed after retries: {last}")

    # ---- high-level execute -------------------------------------------------
    def execute(self, query: str, variables: dict | None = None) -> dict:
        resp = self._post({"query": query, "variables": variables or {}})
        ext = resp.get("extensions", {})
        cost = ext.get("cost", {})
        if cost:
            t = cost.get("throttleStatus", {})
            self.throttle = Throttle(
                available=float(t.get("currentlyAvailable", self.throttle.available)),
                maximum=float(t.get("maximumAvailable", self.throttle.maximum)),
                restore=float(t.get("restoreRate", self.throttle.restore)),
            )
            # Pre-emptive backoff if bucket below 10%
            if self.throttle.available < self.throttle.maximum * 0.1:
                deficit = self.throttle.maximum * 0.5 - self.throttle.available
                wait = max(0.0, deficit / self.throttle.restore)
                if wait > 0:
                    self.log(f"  [throttle] available={self.throttle.available:.0f} -> sleeping {wait:.1f}s")
                    time.sleep(wait)
        if "errors" in resp:
            raise RuntimeError(f"GraphQL errors: {resp['errors']}")
        return resp["data"]
