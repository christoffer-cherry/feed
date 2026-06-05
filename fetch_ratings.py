"""
Fetch Lipscore Google Shopping XML feed, aggregate ratings per product,
and write docs/ratings.json + docs/ratings.csv for GitHub Pages.

Required env vars:
  LIPSCORE_XML_URL   — full URL to the export.xml feed
  LIPSCORE_XML_USER  — basic auth username
  LIPSCORE_XML_PASS  — basic auth password
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
    print(f"Fetching XML feed...")
    resp = requests.get(XML_URL, auth=(XML_USER, XML_PASS), timeout=60)
    print(f"  Status: {resp.status_code}  Size: {len(resp.content)} bytes")
    if resp.status_code != 200:
        sys.exit(f"ERROR: Got {resp.status_code}. Body: {resp.text[:300]}")
    return resp.text


def aggregate(xml_text: str) -> list[dict]:
    """Parse XML and compute avg rating + review count per product."""
    root = ET.fromstring(xml_text)

    # Collect all namespaces used in the document
    ns = {}
    for prefix, uri in ET.iterparse.__doc__ and [] or []:
        ns[prefix] = uri

    # Print root tag so we can see the structure
    print(f"  Root tag: {root.tag}")
    if len(root) > 0:
        first = root[0]
        print(f"  First child tag: {first.tag}")
        print(f"  First child children: {[c.tag for c in first][:10]}")

    # Ratings accumulator: product_id -> [rating, rating, ...]
    ratings_map = defaultdict(list)

    # Try multiple XML structures Lipscore might use
    # Strategy 1: Google Shopping Product Reviews feed
    # <entry><g:id>...</g:id><g:rating>...</g:rating></entry>
    g_ns = "http://base.google.com/ns/1.0"

    for entry in root.iter("entry"):
        product_id = None
        rating = None

        # Try g:id / g:rating (Google Shopping format)
        id_el = entry.find(f"{{{g_ns}}}id") or entry.find("id")
        rating_el = entry.find(f"{{{g_ns}}}rating") or entry.find("rating")

        if id_el is not None:
            product_id = (id_el.text or "").strip()
        if rating_el is not None:
            try:
                rating = float(rating_el.text)
            except (TypeError, ValueError):
                pass

        if product_id and rating is not None:
            ratings_map[product_id].append(rating)

    # Strategy 2: Google Customer Reviews format
    # <review><products><product><product_ids><skus><sku>...</sku>...
    # <ratings><overall>4</overall></ratings>
    if not ratings_map:
        for review in root.iter("review"):
            rating = None
            overall = review.find(".//overall")
            if overall is not None:
                try:
                    rating = float(overall.text)
                except (TypeError, ValueError):
                    pass

            if rating is None:
                continue

            # Collect all product IDs mentioned in this review
            for sku in review.findall(".//sku"):
                if sku.text:
                    ratings_map[sku.text.strip()].append(rating)
            for gtin in review.findall(".//gtin"):
                if gtin.text:
                    ratings_map[gtin.text.strip()].append(rating)
            for mpn in review.findall(".//mpn"):
                if mpn.text:
                    ratings_map[mpn.text.strip()].append(rating)

    print(f"  Unique products found: {len(ratings_map)}")

    if not ratings_map:
        # Dump a sample of the XML to help diagnose structure
        print("  WARNING: Could not parse any ratings. Raw XML sample:")
        print(xml_text[:1000])

    records = []
    for product_id, ratings in sorted(ratings_map.items()):
        avg = round(sum(ratings) / len(ratings), 2)
        records.append({
            "product_id": product_id,
            "avg_rating": avg,
            "review_count": len(ratings),
        })

    return records


def main():
    xml_text = fetch_xml()
    records = aggregate(xml_text)
    print(f"Total products with ratings: {len(records)}")

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

    # Minimal index page
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
