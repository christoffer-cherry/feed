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

    for entry in entries:
        # --- Rating ---
        # Google PRF v2: <ratings><overall>4</overall></ratings>
        rating = None
        ratings_el = find(entry, "ratings")
        if ratings_el is not None:
            rating = findtext(ratings_el, "overall")
        if rating is None:
            rating = findtext(entry, "rating") or findtext(entry, "score")

        # --- Product ID ---
        # Google PRF v2: <products><product><product_ids><skus><sku>ID</sku></skus></product_ids></product></products>
        product_id = None
        products_el = find(entry, "products")
        if products_el is not None:
            product_el = find(products_el, "product")
            if product_el is not None:
                pid_el = find(product_el, "product_ids")
                if pid_el is not None:
                    # Try skus first, then gtins
                    for container_name, leaf_name in [("skus", "sku"), ("gtins", "gtin"), ("mpns", "mpn")]:
                        cont = find(pid_el, container_name)
                        if cont is not None:
                            leaf = find(cont, leaf_name)
                            if leaf is not None and leaf.text:
                                product_id = leaf.text.strip()
                                break
                    # Fallback: direct product_id child
                    if not product_id:
                        product_id = findtext(pid_el, "product_id")

        # Fallback: direct fields on entry
        if not product_id:
            product_id = (
                findtext(entry, "product_id")
                or findtext(entry, "external_id")
                or findtext(entry, "internal_id")
                or findtext(entry, "sku")
            )

        if not product_id or rating is None:
            continue

        try:
            buckets[str(product_id)].append(float(rating))
        except (ValueError, TypeError):
            continue

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
