#!/usr/bin/env python3
"""Download TEA district boundaries from ArcGIS, simplify for web, export as GeoJSON.

Run outside Docker in a virtualenv:
    pip install -r scripts/requirements-boundaries.txt
    python scripts/boundaries/download_tea_boundaries.py

Outputs: data/boundaries/districts.geojson
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

import geopandas as gpd
import requests

# TEA ArcGIS FeatureServer — "SchoolDistricts_SY2425" layer (via Current Districts item)
# Verified fields: DISTRICT_C (6-digit TEA ID), NAME (district name)
# No region/county fields in this layer — we join from TEA SQLite
FEATURE_SERVER_URL = (
    "https://services2.arcgis.com/5MVN2jsqIrNZD4tP"
    "/arcgis/rest/services/Map/FeatureServer/0/query"
)

BATCH_SIZE = 1000
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "boundaries"
OUTPUT_FILE = OUTPUT_DIR / "districts.geojson"
TEA_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "tea_data.db"

# Simplification tolerance in degrees (~0.001 deg ≈ 111m)
SIMPLIFY_TOLERANCE = 0.001


def fetch_all_features() -> list[dict]:
    """Download all features from ArcGIS FeatureServer with pagination."""
    all_features = []
    offset = 0

    print("Fetching features from TEA ArcGIS FeatureServer...")

    while True:
        params = {
            "where": "1=1",
            "outFields": "DISTRICT_C,NAME",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": BATCH_SIZE,
            "outSR": "4326",
        }

        data = None
        for attempt in range(3):
            try:
                resp = requests.get(FEATURE_SERVER_URL, params=params, timeout=120)
                resp.raise_for_status()
                data = resp.json()
                break
            except (requests.RequestException, json.JSONDecodeError) as e:
                if attempt < 2:
                    print(f"  Retry {attempt + 1}/3 after error: {e}")
                    time.sleep(5 * (attempt + 1))
                else:
                    print(f"  FATAL: Failed after 3 attempts at offset {offset}: {e}")
                    sys.exit(1)

        if data is None:
            break

        features = data.get("features", [])
        if not features:
            break

        all_features.extend(features)
        print(f"  Fetched {len(all_features)} features (batch of {len(features)} at offset {offset})")

        # Check if there are more
        exceeded = data.get("properties", {}).get("exceededTransferLimit", False)
        if not exceeded and len(features) < BATCH_SIZE:
            break

        offset += len(features)

    print(f"Total features downloaded: {len(all_features)}")
    return all_features


def inspect_fields(features: list[dict]):
    """Print all field names and 3 sample features to verify TEA ID field."""
    if not features:
        print("No features to inspect!")
        return

    props = features[0].get("properties", {})
    print("\n=== FIELD NAMES ===")
    for key in sorted(props.keys()):
        print(f"  {key}: {type(props[key]).__name__} = {repr(props[key])}")

    print("\n=== SAMPLE FEATURES (first 3) ===")
    for i, feat in enumerate(features[:3]):
        print(f"\n--- Feature {i + 1} ---")
        for key, val in feat.get("properties", {}).items():
            print(f"  {key}: {repr(val)}")


def process_boundaries(features: list[dict]) -> gpd.GeoDataFrame:
    """Load features into GeoDataFrame, simplify, and add region/county from TEA DB."""
    print(f"\nProcessing {len(features)} features...")

    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")

    print(f"  CRS: {gdf.crs}")
    print(f"  Columns: {list(gdf.columns)}")

    # Map TEA ID from DISTRICT_C (6-digit string, no dash)
    gdf["tea_id"] = gdf["DISTRICT_C"].astype(str).str.strip().str.zfill(6)
    gdf["name"] = gdf["NAME"]

    # Join region/county from TEA SQLite if available
    if TEA_DB_PATH.exists():
        conn = sqlite3.connect(TEA_DB_PATH)
        tea_df = gpd.pd.read_sql_query(
            "SELECT tea_id, region, county FROM districts", conn
        )
        conn.close()
        gdf = gdf.merge(tea_df, on="tea_id", how="left")
        matched = gdf["region"].notna().sum()
        print(f"  Joined region/county from TEA DB: {matched}/{len(gdf)} matched")
    else:
        gdf["region"] = None
        gdf["county"] = None
        print("  WARNING: TEA DB not found, skipping region/county join")

    # Simplify geometries
    original_vertices = sum(
        len(geom.exterior.coords) if geom.geom_type == "Polygon"
        else sum(len(p.exterior.coords) for p in geom.geoms) if geom.geom_type == "MultiPolygon"
        else 0
        for geom in gdf.geometry
    )

    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)

    simplified_vertices = sum(
        len(geom.exterior.coords) if geom.geom_type == "Polygon"
        else sum(len(p.exterior.coords) for p in geom.geoms) if geom.geom_type == "MultiPolygon"
        else 0
        for geom in gdf.geometry
    )

    reduction = (1 - simplified_vertices / original_vertices) * 100 if original_vertices else 0
    print(f"  Simplified: {original_vertices:,} -> {simplified_vertices:,} vertices ({reduction:.1f}% reduction)")

    # Select only needed columns
    gdf = gdf[["tea_id", "name", "region", "county", "geometry"]]

    return gdf


def linkage_report(gdf: gpd.GeoDataFrame):
    """Report how many boundary features match our organizations."""
    if not TEA_DB_PATH.exists():
        print(f"\nSkipping linkage report: TEA DB not found at {TEA_DB_PATH}")
        return

    conn = sqlite3.connect(TEA_DB_PATH)
    cursor = conn.execute("SELECT tea_id FROM districts")
    tea_ids_in_db = {row[0] for row in cursor}
    conn.close()

    boundary_ids = set(gdf["tea_id"].values)

    matched = boundary_ids & tea_ids_in_db
    boundary_only = boundary_ids - tea_ids_in_db
    db_only = tea_ids_in_db - boundary_ids

    print(f"\n=== LINKAGE REPORT ===")
    print(f"Boundary features: {len(boundary_ids)}")
    print(f"TEA DB districts:  {len(tea_ids_in_db)}")
    print(f"Matched:           {len(matched)}")
    print(f"In boundaries only: {len(boundary_only)}")
    print(f"In DB only:         {len(db_only)}")

    if boundary_only:
        print(f"\nSample boundary-only IDs: {sorted(boundary_only)[:10]}")
    if db_only:
        print(f"\nSample DB-only IDs: {sorted(db_only)[:10]}")


def main():
    features = fetch_all_features()

    if not features:
        print("No features downloaded!")
        sys.exit(1)

    # Inspect fields first
    inspect_fields(features)

    # Process
    gdf = process_boundaries(features)

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    gdf.to_file(OUTPUT_FILE, driver="GeoJSON")

    file_size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)
    print(f"\nSaved to {OUTPUT_FILE}")
    print(f"File size: {file_size_mb:.1f} MB")
    print(f"Features: {len(gdf)}")

    # Linkage report
    linkage_report(gdf)


if __name__ == "__main__":
    main()
