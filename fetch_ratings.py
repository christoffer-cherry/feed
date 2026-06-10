"""
DIAGNOSTIC: Probe Lipscore API to find correct endpoint and field names for ratings.

Tries multiple approaches and logs the full responses so we can identify what works.

Required env vars:
  LIPSCORE_PUBLIC_KEY   — public API key (api_key query param)
  LIPSCORE_SECRET_KEY   — secret API key (X-Authorization header)
"""

import csv
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

PUBLIC_KEY = os.environ.get("LIPSCORE_PUBLIC_KEY")
SECRET_KEY = os.environ.get("LIPSCORE_SECRET_KEY")

for var, val in [("LIPSCORE_PUBLIC_KEY", PUBLIC_KEY), ("LIPSCORE_SECRET_KEY", SECRET_KEY)]:
    if not val:
        sys.exit(f"ERROR: {var} environment variable is not set.")

BASE_URL = "https://api.lipscore.com"
DOCS_DIR = Path(__file__).parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)

# Product-IDs seen in the Lipscore dashboard (confirmed to have reviews)
KNOWN_PRODUCT_IDS = ["10068807844120", "10068813218072", "9425864622360"]


def get(path, params=None, headers=None):
    default_headers = {"X-Authorization": SECRET_KEY}
    if headers:
        default_headers.update(headers)
    default_params = {"api_key": PUBLIC_KEY}
    if params:
        default_params.update(params)
    resp = requests.get(f"{BASE_URL}{path}", headers=default_headers, params=default_params, timeout=30)
    return resp


def get_public_only(path, params=None):
    """Call with public key only — no secret key header."""
    default_params = {"api_key": PUBLIC_KEY}
    if params:
        default_params.update(params)
    resp = requests.get(f"{BASE_URL}{path}", params=default_params, timeout=30)
    return resp


def probe(label, resp):
    print(f"\n--- {label} ---")
    print(f"  Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        if isinstance(data, list):
            print(f"  List of {len(data)} items")
            if data:
                print(f"  First item keys: {list(data[0].keys())}")
                print(f"  First item: {json.dumps(data[0], indent=2)[:500]}")
        elif isinstance(data, dict):
            print(f"  Dict keys: {list(data.keys())}")
            print(f"  Data: {json.dumps(data, indent=2)[:500]}")
    else:
        print(f"  Body: {resp.text[:200]}")
    return resp.status_code == 200, resp


def main():
    print("=" * 60)
    print("LIPSCORE API DIAGNOSTIC")
    print("=" * 60)

    results = {}

    # --- 1. Individual product lookup (by known dashboard Product-IDs) ---
    print("\n[1] Individual product endpoints (with full auth):")
    for pid in KNOWN_PRODUCT_IDS:
        ok, r = probe(f"GET /products/{pid}/", get(f"/products/{pid}/"))
        if ok:
            results["individual_product"] = r.json()
            break

    # --- 2. Individual product lookup (public key only) ---
    print("\n[2] Individual product endpoints (public key only):")
    for pid in KNOWN_PRODUCT_IDS:
        ok, r = probe(f"GET /products/{pid}/ (public only)", get_public_only(f"/products/{pid}/"))
        if ok:
            results["individual_product_public"] = r.json()
            break

    # --- 3. Products list with public key only (no secret header) ---
    print("\n[3] Products list (public key only, no secret):")
    ok, r = probe("GET /products/ (public only)", get_public_only("/products/", {"page": 1, "per_page": 3}))
    if ok:
        results["products_public"] = r.json()

    # --- 4. Products list filtered by has_reviews ---
    print("\n[4] Products list with has_reviews filter:")
    for param_name in ["has_reviews", "with_reviews", "votes_min", "min_votes"]:
        ok, r = probe(f"GET /products/?{param_name}=1", get(f"/products/", {"page": 1, "per_page": 3, param_name: 1}))
        if ok and r.json():
            data = r.json() if isinstance(r.json(), list) else []
            if data and data[0].get("rating") is not None:
                print(f"  *** FOUND RATINGS with param {param_name}! ***")
                results["products_filtered"] = r.json()
            break

    # --- 5. Product ratings endpoint ---
    print("\n[5] Dedicated ratings endpoints:")
    for path in ["/ratings/", "/product_ratings/", "/products/ratings/", "/aggregations/"]:
        ok, r = probe(f"GET {path}", get(path, {"page": 1, "per_page": 3}))
        if ok:
            results[f"ratings_endpoint_{path}"] = r.json()
            break

    # --- 6. Service reviews (might give a clue about the data structure) ---
    print("\n[6] Service reviews endpoint:")
    for path in ["/service_reviews/", "/surveys/"]:
        ok, r = probe(f"GET {path}", get(path, {"page": 1, "per_page": 3}))
        if ok:
            results[f"service_reviews_{path}"] = r.json()
            break

    # --- 7. Votes endpoint ---
    print("\n[7] Votes endpoints:")
    for path in ["/votes/", "/product_votes/"]:
        ok, r = probe(f"GET {path}", get(path, {"page": 1, "per_page": 3}))
        if ok:
            results[f"votes_{path}"] = r.json()
            break

    # --- 8. First 3 products from normal products list (with secret key) ---
    print("\n[8] First 3 products (normal auth, for comparison):")
    ok, r = probe("GET /products/ (normal, per_page=3)", get("/products/", {"page": 1, "per_page": 3}))
    if ok:
        results["products_normal_sample"] = r.json()

    # Write diagnostic results to docs/
    diag_path = DOCS_DIR / "diagnostic.json"
    diag_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n\nDiagnostic results written to: {diag_path}")
    print("Check https://christoffer-cherry.github.io/feed/diagnostic.json for full output")


if __name__ == "__main__":
    main()
