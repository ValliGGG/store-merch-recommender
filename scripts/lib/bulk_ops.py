"""Shopify bulk operation runner + JSONL streaming parser.

Bulk ops let us pull tens of thousands of orders in one call. We poll until
the operation completes, download the JSONL result, and yield records.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator
from urllib import request as urlreq

from .shopify_client import ShopifyClient


def start(client: ShopifyClient, query: str) -> str:
    """Run a bulk query.  Returns the bulk operation id."""
    mutation = """
    mutation BulkRun($q: String!) {
      bulkOperationRunQuery(query: $q) {
        bulkOperation { id status }
        userErrors { field message }
      }
    }
    """
    data = client.execute(mutation, {"q": query})
    op = data["bulkOperationRunQuery"]
    if op["userErrors"]:
        raise RuntimeError(f"bulk start errors: {op['userErrors']}")
    return op["bulkOperation"]["id"]


def current(client: ShopifyClient) -> dict | None:
    """Return the current bulk op (any status), or None if there isn't one."""
    q = """
    {
      currentBulkOperation {
        id status errorCode createdAt completedAt objectCount fileSize url
      }
    }
    """
    return client.execute(q)["currentBulkOperation"]


_NODE_Q = """
query Op($id: ID!) {
  node(id: $id) {
    ... on BulkOperation {
      id status errorCode createdAt completedAt objectCount fileSize url
    }
  }
}
"""


def get_by_id(client: ShopifyClient, op_id: str) -> dict | None:
    """Look up a specific bulk op by ID — survives preemption by other apps."""
    return client.execute(_NODE_Q, {"id": op_id})["node"]


def wait_for_completion(client: ShopifyClient, op_id: str, *, log=print, poll_seconds: int = 15) -> dict:
    """Block until the specified bulk op finishes; raises on preemption.

    Polls the specific op via node(id:) instead of currentBulkOperation, so we
    detect when another bulk op preempts ours (Shopify only allows one running
    op per shop — the existing one gets cancelled when a new one starts).
    """
    while True:
        op = get_by_id(client, op_id)
        if not op:
            raise RuntimeError(f"bulk op {op_id} disappeared from API")
        status = op["status"]
        log(f"  [bulk] {op_id.split('/')[-1]} status={status} objects={op.get('objectCount')} size={op.get('fileSize')}")
        if status == "COMPLETED":
            return op
        if status == "CANCELED":
            raise RuntimeError(
                f"bulk op {op_id} was CANCELED — another bulk op preempted us. "
                f"errorCode={op.get('errorCode')}.  Re-run after the competing op finishes."
            )
        if status in ("FAILED", "EXPIRED"):
            raise RuntimeError(f"bulk op ended badly: {op}")
        time.sleep(poll_seconds)


def download_jsonl(url: str, dest: Path, *, log=print) -> Path:
    """Download a bulk op result file to disk (streaming)."""
    log(f"  [bulk] downloading -> {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urlreq.urlopen(url, timeout=300) as r, dest.open("wb") as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    log(f"  [bulk] downloaded {dest.stat().st_size:,} bytes")
    return dest


def iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
