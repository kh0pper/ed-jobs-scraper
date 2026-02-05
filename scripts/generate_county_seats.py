#!/usr/bin/env python3
"""Fetch Texas county seats from Wikidata and update JSON file."""
import json
import sys
from pathlib import Path

import requests

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"

# SPARQL query to get all Texas counties and their county seats
# Q11774097 = county of Texas (specific class)
# P36 = capital (county seat)
QUERY = """
SELECT ?countyLabel ?seatLabel WHERE {
  ?county wdt:P31 wd:Q11774097 .  # instance of: county of Texas
  ?county wdt:P36 ?seat .          # capital (county seat)
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
ORDER BY ?countyLabel
"""


def fetch_county_seats() -> dict[str, str]:
    """Fetch Texas county seats from Wikidata SPARQL endpoint."""
    print("Fetching county seats from Wikidata...")

    resp = requests.get(
        WIKIDATA_ENDPOINT,
        params={"query": QUERY, "format": "json"},
        headers={"User-Agent": "EdJobsScraper/1.0 (Texas education job aggregator)"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    result = {}
    for binding in data["results"]["bindings"]:
        county = binding["countyLabel"]["value"]
        seat = binding["seatLabel"]["value"]

        # Clean up county name (remove " County" suffix if present)
        if county.endswith(" County"):
            county = county[:-7]

        result[county] = seat

    return result


def main():
    json_path = Path(__file__).parent.parent / "backend/app/data/texas_county_seats.json"

    if not json_path.exists():
        print(f"Error: JSON file not found at {json_path}")
        sys.exit(1)

    # Load existing data
    with open(json_path) as f:
        existing = json.load(f)
    print(f"Existing counties: {len(existing)}")

    # Fetch from Wikidata
    try:
        wikidata = fetch_county_seats()
    except requests.RequestException as e:
        print(f"Error fetching from Wikidata: {e}")
        sys.exit(1)

    print(f"Counties from Wikidata: {len(wikidata)}")

    # Merge (existing takes precedence for any conflicts)
    merged = {**wikidata, **existing}
    print(f"Merged total: {len(merged)} counties")

    # Report new additions
    new_counties = set(merged.keys()) - set(existing.keys())
    if new_counties:
        print(f"\nNew counties added ({len(new_counties)}):")
        for county in sorted(new_counties)[:10]:
            print(f"  {county} -> {merged[county]}")
        if len(new_counties) > 10:
            print(f"  ... and {len(new_counties) - 10} more")

    # Save
    with open(json_path, "w") as f:
        json.dump(merged, f, indent=2, sort_keys=True)
    print(f"\nSaved to {json_path}")

    # Verify Texas has 254 counties
    if len(merged) < 254:
        print(f"\nWarning: Texas has 254 counties, but only {len(merged)} in file")
    elif len(merged) == 254:
        print("\n✓ All 254 Texas counties now have county seats")


if __name__ == "__main__":
    main()
