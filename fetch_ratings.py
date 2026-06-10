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

    # Log the root tag and first child to understand the XML structure
    print(f"  Root tag: {root.tag}")
    children = list(root)
    if children:
        first = children[0]
        print(f"  First child tag: {first.tag}")
        print(f"  First child attribs: {first.attrib}")
        print(f"  First child sub-elements: {[c.tag for c in first]}")
        # Print full first entry for inspection
        print(f"  First entry XML: {ET.tostring(first, encoding='unicode')[:800]}")

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

    # Accumulate ratings per product_id
    buckets: dict[str, list[float]] = defaultdict(list)

    # Try to handle common review XML formats
    entries = list(root)
    # If root is <feed> with <entry> children (Atom format)
    # or <reviews> with <review> children, etc.
    print(f"  Total top-level entries: {len(entries)}")

    for entry in entries:
        # Try multiple field name patterns
        product_id = (
            findtext(entry, "product_id")
            or findtext(entry, "productId")
            or findtext(entry, "external_id")
            or findtext(entry, "internal_id")
            or findtext(entry, "sku")
        )

        # Check nested product element
        product_el = find(entry, "product")
        if not product_id and product_el is not None:
            product_id = (
                findtext(product_el, "product_id")
                or findtext(product_el, "id")
                or findtext(product_el, "external_id")
                or findtext(product_el, "internal_id")
                or findtext(product_el, "sku")
            )

        # Google Shopping feed: g:product_ids / g:product_id
        if not product_id:
            for child in entry:
                if tag(child) in ("product_ids", "product_id"):
                    for sub in child:
                        if tag(sub) in ("product_id", "gtin", "sku", "id"):
                            product_id = sub.text.strip() if sub.text else None
                            break

        rating = (
            findtext(entry, "rating")
            or findtext(entry, "score")
            or findtext(entry, "grade")
        )

        # Google Shopping: g:ratings/g:overall
        if not rating:
            ratings_el = find(entry, "ratings")
            if ratings_el is not None:
                rating = findtext(ratings_el, "overall")

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
