"""
Fetch aggregated per-product ratings from Lipscore API and write
docs/ratings.json + docs/ratings.csv for GitHub Pages.

Auth (confirmed by Lipscore support):
  - api_key as query parameter  (public API key)
  - X-Authorization header      (secret API key)

Required env vars:
  LIPSCORE_PUBLIC_KEY   — public API key (api_key query param)
  LIPSCORE_SECRET_KEY   — secret API key (X-Authorization header)
"""

import csv
import json
import os
import sys
import time
from pathlib import Path

import requests

PUBLIC_KEY = os.environ.get("LIPSCORE_PUBLIC_KEY")
SECRET_KEY = os.environ.get("LIPSCORE_SECRET_KEY")

for var, val in [("LIPSCORE_PUBLIC_KEY", PUBLIC_KEY), ("LIPSCORE_SECRET_KEY", SECRET_KEY)]:
    if not val:
        sys.exit(f"ERROR: {var} environment variable is not set.")

BASE_URL   = "https://api.lipscore.com"
HEADERS    = {"X-Authorization": SECRET_KEY}
PAGE_SIZE  = 100
DOCS_DIR   = Path(__file__).parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)


def fetch_all_products() -> list[dict]:
    products = []
    page = 1

    while True:
        params = {
            "api_key":  PUBLIC_KEY,
            "page":     page,
            "per_page": PAGE_SIZE,
        }
        resp = requests.get(
            f"{BASE_URL}/products/",
            headers=HEADERS,
            params=params,
            timeout=30,
        )

        print(f"  Page {page}: HTTP {resp.status_code}")

        if resp.status_code != 200:
            sys.exit(f"ERROR: {resp.status_code} — {resp.text[:300]}")

        batch = resp.json()
        if isinstance(batch, dict):
            batch = batch.get("products") or batch.get("data") or []

        if not batch:
            break

        products.extend(batch)
        print(f"    {len(batch)} products (total: {len(products)})")

        # Print keys from first product so we can verify field names
        if page == 1 and batch:
            print(f"    Sample keys: {list(batch[0].keys())}")
            print(f"    Sample product: {batch[0]}")

        if len(batch) < PAGE_SIZE:
            break

        page += 1
        time.sleep(0.2)

    return products


def normalise(product: dict) -> dict | None:
    # Shopify Product ID is stored as external_id / internal_id
    product_id = (
        product.get("external_id")
        or product.get("internal_id")
        or product.get("product_id")
        or product.get("id")
    )
    avg_rating = (
        product.get("avg_rating")
        or product.get("average_rating")
        or product.get("rating")
    )
    review_count = (
        product.get("votes_count")
        or product.get("reviews_count")
        or product.get("review_count")
        or 0
    )

    if not product_id or avg_rating is None:
        return None

    return {
        "product_id":   str(product_id),
        "avg_rating":   round(float(avg_rating), 2),
        "review_count": int(review_count),
    }


def main():
    print("Fetching products from Lipscore API...")
    raw = fetch_all_products()
    print(f"Total products fetched: {len(raw)}")

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
    index_path.write_text(
        "<html><body>"
        f"<p>{len(records)} products with ratings.</p>"
        "<p><a href='ratings.json'>ratings.json</a></p>"
        "<p><a href='ratings.csv'>ratings.csv</a></p>"
        "</body></html>",
        encoding="utf-8",
    )
    print("Done.")


if __name__ == "__main__":
    main()
