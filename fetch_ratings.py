"""
Fetch per-product ratings from Lipscore by aggregating individual reviews.

Uses /reviews/ endpoint (not /products/) because the products list endpoint
does not populate rating aggregates for this account.

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
from collections import defaultdict
from pathlib import Path

import requests

PUBLIC_KEY = os.environ.get("LIPSCORE_PUBLIC_KEY")
SECRET_KEY = os.environ.get("LIPSCORE_SECRET_KEY")

for var, val in [("LIPSCORE_PUBLIC_KEY", PUBLIC_KEY), ("LIPSCORE_SECRET_KEY", SECRET_KEY)]:
    if not val:
        sys.exit(f"ERROR: {var} environment variable is not set.")

BASE_URL  = "https://api.lipscore.com"
HEADERS   = {"X-Authorization": SECRET_KEY}
PAGE_SIZE = 100
DOCS_DIR  = Path(__file__).parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)


def fetch_all_reviews() -> list[dict]:
    """Fetch all product reviews from Lipscore /reviews/ endpoint."""
    reviews = []
    page = 1

    while True:
        params = {
            "api_key":  PUBLIC_KEY,
            "page":     page,
            "per_page": PAGE_SIZE,
            "type":     "product",   # only product reviews, not service reviews
        }
        resp = requests.get(
            f"{BASE_URL}/reviews/",
            headers=HEADERS,
            params=params,
            timeout=30,
        )

        print(f"  Page {page}: HTTP {resp.status_code}", end=" ")

        if resp.status_code == 500:
            print(f"— server error. Saving {len(reviews)} reviews fetched so far.")
            break
        if resp.status_code != 200:
            sys.exit(f"\nERROR: {resp.status_code} — {resp.text[:300]}")

        batch = resp.json()
        if isinstance(batch, dict):
            batch = batch.get("reviews") or batch.get("data") or []

        print(f"— {len(batch)} reviews (total: {len(reviews) + len(batch)})")

        if not batch:
            break

        reviews.extend(batch)

        # Log first review to verify field names
        if page == 1 and batch:
            print(f"    Sample keys: {list(batch[0].keys())}")
            print(f"    Sample review: {batch[0]}")

        if len(batch) < PAGE_SIZE:
            break

        page += 1
        time.sleep(0.2)

    return reviews


def aggregate_by_product(reviews: list[dict]) -> list[dict]:
    """Group reviews by product_id and compute avg_rating + review_count."""
    buckets: dict[str, list[float]] = defaultdict(list)

    for r in reviews:
        # Product-ID field names to try (check sample log to confirm)
        product_id = (
            r.get("product_id")
            or r.get("product", {}).get("id") if isinstance(r.get("product"), dict) else None
            or r.get("product", {}).get("internal_id") if isinstance(r.get("product"), dict) else None
            or r.get("internal_id")
        )
        rating = r.get("rating") or r.get("score")

        if not product_id or rating is None:
            continue

        try:
            buckets[str(product_id)].append(float(rating))
        except (ValueError, TypeError):
            continue

    records = []
    for product_id, ratings in buckets.items():
        records.append({
            "product_id":   product_id,
            "avg_rating":   round(sum(ratings) / len(ratings), 2),
            "review_count": len(ratings),
        })

    return sorted(records, key=lambda x: x["product_id"])


def main():
    print("Fetching reviews from Lipscore API...")
    raw_reviews = fetch_all_reviews()
    print(f"Total reviews fetched: {len(raw_reviews)}")

    records = aggregate_by_product(raw_reviews)
    print(f"Products with ratings: {len(records)}")

    if records:
        print(f"  Sample output: {records[:3]}")

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
