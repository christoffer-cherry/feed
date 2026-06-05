"""
Fetch aggregated per-product ratings from Lipscore API and write
docs/ratings.json + docs/ratings.csv for GitHub Pages.

Requires env var: LIPSCORE_API_KEY
"""

import csv
import json
import os
import sys
import time
from pathlib import Path

import requests

API_KEY = os.environ.get("LIPSCORE_API_KEY")
if not API_KEY:
    sys.exit("ERROR: LIPSCORE_API_KEY environment variable is not set.")

BASE_URL = "https://api.lipscore.com"
HEADERS = {"X-Authorization": API_KEY}
PAGE_SIZE = 100
DOCS_DIR = Path(__file__).parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)


def fetch_all_products() -> list[dict]:
    """Paginate through /products and return all entries."""
    products = []
    page = 1

    while True:
        resp = requests.get(
            f"{BASE_URL}/products",
            headers=HEADERS,
            params={"page": page, "per_page": PAGE_SIZE},
            timeout=30,
        )

        if resp.status_code == 401:
            sys.exit(f"ERROR: 401 Unauthorized. Response: {resp.text}")
        resp.raise_for_status()

        batch = resp.json()

        # Handle both list and dict-wrapped responses
        if isinstance(batch, dict):
            batch = batch.get("products") or batch.get("data") or []

        if not batch:
            break

        products.extend(batch)
        print(f"  Page {page}: {len(batch)} products (total so far: {len(products)})")

        if len(batch) < PAGE_SIZE:
            break

        page += 1
        time.sleep(0.2)  # be polite to the API

    return products


def normalise(product: dict) -> dict | None:
    """Extract the fields we care about. Returns None if no ratings yet."""
    # Lipscore may use different field names across API versions
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
    print("Fetching products from Lipscore API...")
    raw = fetch_all_products()
    print(f"Total raw products fetched: {len(raw)}")

    records = [r for p in raw if (r := normalise(p)) is not None]
    print(f"Products with ratings: {len(records)}")

    if not records:
        print("WARNING: No rated products found. Output files will be empty.")

    # Write JSON
    json_path = DOCS_DIR / "ratings.json"
    json_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Written: {json_path}")

    # Write CSV
    csv_path = DOCS_DIR / "ratings.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["product_id", "avg_rating", "review_count"])
        writer.writeheader()
        writer.writerows(records)
    print(f"Written: {csv_path}")

    # Write a tiny index so GitHub Pages has a root page
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
