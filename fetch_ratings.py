"""
Fetch per-product ratings from Lipscore review export XML and write
docs/ratings.json + docs/ratings.csv for GitHub Pages.

Aggregates individual reviews by product ID to produce avg_rating + review_count.

Required env vars:
  LIPSCORE_XML_URL    — full URL to the Lipscore export XML
  LIPSCORE_XML_USER   — Lipscore account username / email (for Basic Auth)
  LIPSCORE_XML_PASS   — Lipscore account password (for Basic Auth)
"""

import csv
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import requests

XML_URL  = os.environ.get("LIPSCORE_XML_URL")
XML_USER = os.environ.get("LIPSCORE_XML_USER")
XML_PASS = os.environ.get("LIPSCORE_XML_PASS")

for var, val in [("LIPSCORE_XML_URL", XML_URL), ("LIPSCORE_XML_USER", XML_USER), ("LIPSCORE_XML_PASS", XML_PASS)]:
    if not val:
        sys.exit(f"ERROR: {var} environment variable is not set.")

DOCS_DIR = Path(__file__).parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)


def fetch_xml() -> str:
    print(f"Fetching XML from Lipscore...")
    resp = requests.get(XML_URL, auth=(XML_USER, XML_PASS), timeout=60)
    print(f"  HTTP {resp.status_code}, {len(resp.content)} bytes")
    if resp.status_code != 200:
        sys.exit(f"ERROR: {resp.status_code} — {resp.text[:300]}")
    return resp.text


_shopify_id_cache: dict[str, str | None] = {}

def shopify_product_id_from_url(product_url: str) -> str | None:
    """
    Fetch Shopify Product ID from a public product URL.
    e.g. https://vipatur.no/products/some-handle
         → https://vipatur.no/products/some-handle.json
         → product["id"]
    """
    if product_url in _shopify_id_cache:
        return _shopify_id_cache[product_url]

    json_url = product_url.rstrip("/") + ".json"
    for attempt in range(4):
        try:
            resp = requests.get(json_url, timeout=15)
            if resp.status_code == 200:
                pid = str(resp.json()["product"]["id"])
                _shopify_id_cache[product_url] = pid
                return pid
            if resp.status_code == 404:
                break  # product doesn't exist, no point retrying
            if resp.status_code == 429:
                time.sleep(2 ** attempt)  # exponential backoff on rate limit
                continue
        except Exception:
            time.sleep(1)
    _shopify_id_cache[product_url] = None
    return None


def parse_and_aggregate(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)

    # Strip namespace from tags if present (e.g. {http://...}tag → tag)
    def tag(el):
        return el.tag.split('}', 1)[-1] if '}' in el.tag else el.tag

    def find(el, name):
        """Find child by local name, ignoring namespace."""
        for child in el:
            if tag(child) == name:
                return child
        return None

    def findtext(el, name):
        child = find(el, name)
        return child.text.strip() if child is not None and child.text else None

    # Log the root tag and all top-level children to understand the XML structure
    print(f"  Root tag: {root.tag}")
    top_children = list(root)
    print(f"  Top-level children ({len(top_children)}): {[tag(c) for c in top_children]}")
    for child in top_children:
        grandchildren = list(child)
        print(f"    <{tag(child)}> has {len(grandchildren)} children")
        if grandchildren:
            first_gc = grandchildren[0]
            print(f"      First grandchild tag: {tag(first_gc)}")
            print(f"      First grandchild sub-elements: {[tag(c) for c in first_gc]}")
            print(f"      First grandchild XML: {ET.tostring(first_gc, encoding='unicode')[:600]}")
            break  # only show first non-empty container

    # Accumulate ratings per product_id
    buckets: dict[str, list[float]] = defaultdict(list)

    # Find <reviews> container
    reviews_el = find(root, "reviews")
    if reviews_el is None:
        # Fallback: use the container with the most children
        reviews_el = max(top_children, key=lambda c: len(list(c)), default=root)

    entries = list(reviews_el)
    print(f"  Parsing {len(entries)} entries from <{tag(reviews_el)}>")

    # Log first entry to verify field structure
    if entries:
        print(f"  First entry XML:\n{ET.tostring(entries[0], encoding='unicode')[:1200]}")

    # First pass: collect (product_url, rating) pairs
    url_ratings: list[tuple[str, float]] = []
    skipped = 0

    for entry in entries:
        # --- Rating ---
        rating = None
        ratings_el = find(entry, "ratings")
        if ratings_el is not None:
            rating = findtext(ratings_el, "overall")
        if rating is None:
            rating = findtext(entry, "rating") or findtext(entry, "score")

        # --- Product URL (used to look up Shopify Product ID) ---
        product_url = None
        products_el = find(entry, "products")
        if products_el is not None:
            product_el = find(products_el, "product")
            if product_el is not None:
                product_url = findtext(product_el, "product_url")

        if not product_url or rating is None:
            skipped += 1
            continue

        try:
            url_ratings.append((product_url, float(rating)))
        except (ValueError, TypeError):
            skipped += 1

    print(f"  Reviews with product URL + rating: {len(url_ratings)} (skipped: {skipped})")

    # Deduplicate URLs to minimise Shopify API calls
    unique_urls = list(dict.fromkeys(u for u, _ in url_ratings))
    print(f"  Unique product URLs: {len(unique_urls)} — resolving Shopify Product IDs...")

    for i, url in enumerate(unique_urls, 1):
        shopify_product_id_from_url(url)
        if i % 10 == 0:
            print(f"    Resolved {i}/{len(unique_urls)}...")
            time.sleep(0.5)  # be polite to Shopify

    print(f"  Resolved {len(_shopify_id_cache)} URLs, "
          f"{sum(1 for v in _shopify_id_cache.values() if v)} succeeded")

    # Second pass: aggregate by Shopify Product ID
    for product_url, rating_val in url_ratings:
        shopify_id = _shopify_id_cache.get(product_url)
        if not shopify_id:
            continue
        buckets[shopify_id].append(rating_val)

    print(f"  Unique products found: {len(buckets)}")

    records = []
    for product_id, ratings in sorted(buckets.items()):
        records.append({
            "product_id":   product_id,
            "avg_rating":   round(sum(ratings) / len(ratings), 2),
            "review_count": len(ratings),
        })

    return records


def main():
    xml_text = fetch_xml()
    print("Parsing XML and aggregating ratings...")
    records = parse_and_aggregate(xml_text)
    print(f"Products with ratings: {len(records)}")

    if records:
        print(f"  Sample: {records[:3]}")

    json_path = DOCS_DIR / "ratings.json"
    json_path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )
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
