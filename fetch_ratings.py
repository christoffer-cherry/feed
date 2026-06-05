"""
Fetch aggregated per-product ratings from Lipscore API and write
docs/ratings.json + docs/ratings.csv for GitHub Pages.

Requires env vars:
  LIPSCORE_API_KEY        — the Secret API key from Lipscore settings
  LIPSCORE_PUBLIC_KEY     — the public API key from Lipscore settings
"""

import csv
import json
import os
import sys
import time
from pathlib import Path

import requests

SECRET_KEY = os.environ.get("LIPSCORE_API_KEY")       # Secret API key
PUBLIC_KEY = os.environ.get("LIPSCORE_PUBLIC_KEY")    # Public API key

if not SECRET_KEY:
    sys.exit("ERROR: LIPSCORE_API_KEY environment variable is not set.")

BASE_URL = "https://api.lipscore.com"
PAGE_SIZE = 100
DOCS_DIR = Path(__file__).parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)


def try_request(url, headers, params):
    """Make a GET request and return (response, error_string)."""
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        return resp, None
    except Exception as e:
        return None, str(e)


def fetch_all_products() -> list[dict]:
    """Try multiple auth approaches until one works, then paginate."""

    # Auth strategies to try in order
    strategies = [
        ("X-Authorization: secret key",
         {"X-Authorization": SECRET_KEY}),
        ("X-Authorization: public key",
         {"X-Authorization": PUBLIC_KEY} if PUBLIC_KEY else None),
        ("Both headers",
         {"X-Authorization": PUBLIC_KEY, "X-Secret": SECRET_KEY} if PUBLIC_KEY else None),
        ("Authorization Bearer: secret key",
         {"Authorization": f"Bearer {SECRET_KEY}"}),
        ("Authorization Bearer: public key",
         {"Authorization": f"Bearer {PUBLIC_KEY}"} if PUBLIC_KEY else None),
    ]

    working_headers = None

    print("--- Probing auth strategies ---")
    for name, headers in strategies:
        if headers is None:
            print(f"  SKIP  {name} (missing key)")
            continue
        resp, err = try_request(
            f"{BASE_URL}/products",
            headers=headers,
            params={"page": 1, "per_page": 1},
        )
        if err:
            print(f"  ERROR {name}: {err}")
            continue
        print(f"  {resp.status_code}   {name}  →  {resp.text[:120]}")
        if resp.status_code == 200:
            working_headers = headers
            print(f"  ✓ Using: {name}")
            break

    if working_headers is None:
        sys.exit("ERROR: All auth strategies returned non-200. See log above.")

    print("--- Fetching all products ---")
    products = []
    page = 1
    while True:
        resp = requests.get(
            f"{BASE_URL}/products",
            headers=working_headers,
            params={"page": page, "per_page": PAGE_SIZE},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if isinstance(batch, dict):
            batch = batch.get("products") or batch.get("data") or []
        if not batch:
            break
        products.extend(batch)
        print(f"  Page {page}: {len(batch)} products (total: {len(products)})")
        if len(batch) < PAGE_SIZE:
            break
        page += 1
        time.sleep(0.2)

    return products


def normalise(product: dict) -> dict | None:
    product_id = (
        product.get("external_id")
        or product.get("product_id")
        or product.get("id")
    )
    avg_rating = product.get("avg_rating") or product.get("average_rating")
    review_count = (
        product.get("votes_count")
        or product.get("reviews_count")
        or product.get("review_count")
        or 0
    )
    if not product_id or avg_rating is None:
        return None
    return {
        "product_id": str(product_id),
        "avg_rating": round(float(avg_rating), 2),
        "review_count": int(review_count),
    }


def main():
    raw = fetch_all_products()
    print(f"Total raw products: {len(raw)}")
    if raw:
        print(f"Sample keys: {list(raw[0].keys())}")

    records = [r for p in raw if (r := normalise(p)) is not None]
    print(f"Products with ratings: {len(records)}")

    json_path = DOCS_DIR / "ratings.json"
    json_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Written: {json_path}")

    csv_path = DOCS_DIR / "ratings.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["product_id", "avg_rating", "review_count"])
        writer.writeheader()
        writer.writerows(records)
    print(f"Written: {csv_path}")

    index_path = DOCS_DIR / "index.html"
    if not index_path.exists():
        index_path.write_text(
            "<html><body>"
            "<p><a href='ratings.json'>ratings.json</a></p>"
            "<p><a href='ratings.csv'>ratings.csv</a></p>"
            "</body></html>",
            encoding="utf-8",
        )
    print("Done.")


if __name__ == "__main__":
    main()
