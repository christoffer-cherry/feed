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
DOCS_DIR   = Path(__file__).parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)


def fetch_page(page: int, per_page: int) -> tuple[int, list]:
    """Fetch a single page. Returns (status_code, batch_list)."""
    params = {
        "api_key":  PUBLIC_KEY,
        "page":     page,
        "per_page": per_page,
    }
    resp = requests.get(
        f"{BASE_URL}/products/",
        headers=HEADERS,
        params=params,
        timeout=30,
    )
    if resp.status_code != 200:
        return resp.status_code, []
    batch = resp.json()
    if isinstance(batch, dict):
        batch = batch.get("products") or batch.get("data") or []
    return 200, batch


def fetch_all_products() -> list[dict]:
    products = []
    page = 1
    page_size = 50   # smaller pages to avoid the 500 on page 4 with per_page=100

    while True:
        print(f"  Page {page} (per_page={page_size})...", end=" ")
        status, batch = fetch_page(page, page_size)

        if status == 500:
            # Try cutting the page in half and re-fetching as smaller chunks
            smaller = page_size // 2
            if smaller < 5:
                print(f"HTTP 500 — cannot reduce page size further. Stopping at {len(products)} products.")
                break
            print(f"HTTP 500 — retrying with per_page={smaller}")
            # Re-fetch this page range as two smaller pages
            for sub_page_offset in range(2):
                # Convert to offset-based sub-pages
                offset_page = (page - 1) * page_size // smaller + sub_page_offset + 1
                sub_status, sub_batch = fetch_page(offset_page, smaller)
                print(f"    Sub-page {offset_page} (per_page={smaller}): HTTP {sub_status}, {len(sub_batch)} products")
                if sub_status == 200 and sub_batch:
                    products.extend(sub_batch)
                time.sleep(0.3)
            page += 1
            time.sleep(0.3)
            continue

        if status != 200:
            print(f"HTTP {status} — stopping.")
            break

        print(f"HTTP 200, {len(batch)} products (total: {len(products) + len(batch)})")

        if not batch:
            break

        products.extend(batch)

        # Log first product to verify field names
        if page == 1 and batch:
            print(f"    Sample keys: {list(batch[0].keys())}")
            print(f"    Sample product: {batch[0]}")

        if len(batch) < page_size:
            break

        page += 1
        time.sleep(0.2)

    return products


def normalise(product: dict) -> dict | None:
    # internal_id = Shopify Product ID (confirmed by Lipscore support)
    # Fall back to 'id' (Lipscore's own ID) only as last resort
    product_id = (
        product.get("internal_id")
        or product.get("external_id")
        or product.get("product_id")
        or product.get("id")
    )

    # Use explicit None checks — rating=0 is a valid (if rare) value
    avg_rating = product.get("rating")
    if avg_rating is None:
        avg_rating = product.get("avg_rating")
    if avg_rating is None:
        avg_rating = product.get("average_rating")

    # votes = total review count (may be named differently per API version)
    review_count = product.get("review_count")
    if review_count is None:
        review_count = product.get("votes")
    if review_count is None:
        review_count = product.get("votes_count")
    if review_count is None:
        review_count = 0

    # Skip products with no product_id or no rating at all
    if not product_id or avg_rating is None:
        return None

    # Skip products with zero votes — no real reviews
    if int(review_count) == 0:
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
