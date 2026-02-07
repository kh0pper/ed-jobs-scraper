#!/usr/bin/env python3
"""Fix coordinates for TEA headquarters and ESC regional offices.

These organizations should have precise office coordinates,
not city-center fallbacks from the generic geocoder.

Run inside Docker:
    docker compose exec backend python scripts/fix_tea_esc_coordinates.py

Or locally:
    cd backend && python ../scripts/fix_tea_esc_coordinates.py
"""

import sys
from pathlib import Path

# Add backend to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
backend_dir = project_root / "backend"
if backend_dir.exists():
    sys.path.insert(0, str(backend_dir))
else:
    sys.path.insert(0, str(script_dir.parent))

from app.models.base import SyncSessionLocal
from app.models.organization import Organization
from app.models.scrape_source import ScrapeSource  # noqa: F401
from app.models.job_posting import JobPosting
from app.models.scrape_run import ScrapeRun  # noqa: F401


# TEA Headquarters
TEA_HQ = {
    "name_pattern": "Texas Education Agency",
    "latitude": 30.2729,
    "longitude": -97.7404,
    "city": "Austin",
    "address": "1701 N Congress Ave, Austin, TX 78701",
}

# ESC Regional Offices — addresses from TEA website
# https://tea.texas.gov/about-tea/other-services/education-service-centers
ESC_OFFICES = {
    1:  {"lat": 26.3054, "lon": -98.1721, "city": "Edinburg",         "address": "1900 West Schunior, Edinburg, TX 78541"},
    2:  {"lat": 27.7988, "lon": -97.3918, "city": "Corpus Christi",   "address": "209 North Water Street, Corpus Christi, TX 78401"},
    3:  {"lat": 28.8254, "lon": -96.9910, "city": "Victoria",         "address": "1905 Leary Lane, Victoria, TX 77901"},
    4:  {"lat": 29.8380, "lon": -95.4774, "city": "Houston",          "address": "7145 West Tidwell, Houston, TX 77092"},
    5:  {"lat": 30.0814, "lon": -94.1267, "city": "Beaumont",         "address": "350 Pine Street, Suite 500, Beaumont, TX 77701"},
    6:  {"lat": 30.7224, "lon": -95.5519, "city": "Huntsville",       "address": "3332 Montgomery Road, Huntsville, TX 77340"},
    7:  {"lat": 32.3857, "lon": -94.8692, "city": "Kilgore",          "address": "1909 N. Longview Street, Kilgore, TX 75662"},
    8:  {"lat": 32.9955, "lon": -94.9592, "city": "Pittsburg",        "address": "4845 U.S. Highway 271 N., Pittsburg, TX 75686"},
    9:  {"lat": 33.8817, "lon": -98.5310, "city": "Wichita Falls",    "address": "301 Loop 11, Wichita Falls, TX 76306"},
    10: {"lat": 32.9136, "lon": -96.7296, "city": "Richardson",       "address": "400 E. Spring Valley Road, Richardson, TX 75081"},
    11: {"lat": 32.7553, "lon": -97.4602, "city": "White Settlement", "address": "1451 S. Cherry Lane, White Settlement, TX 76108"},
    12: {"lat": 31.5328, "lon": -97.2219, "city": "Waco",             "address": "2101 W. Loop 340, Waco, TX 76712"},
    13: {"lat": 30.3119, "lon": -97.6799, "city": "Austin",           "address": "5701 Springdale Road, Austin, TX 78723"},
    14: {"lat": 32.4478, "lon": -99.7103, "city": "Abilene",          "address": "1850 Highway 351, Abilene, TX 79601"},
    15: {"lat": 31.4413, "lon": -100.4530, "city": "San Angelo",      "address": "612 South Irene Street, San Angelo, TX 76903"},
    16: {"lat": 35.1794, "lon": -101.8544, "city": "Amarillo",        "address": "5800 Bell Street, Amarillo, TX 79109"},
    17: {"lat": 33.5081, "lon": -101.8627, "city": "Lubbock",         "address": "1111 West Loop 289, Lubbock, TX 79416"},
    18: {"lat": 31.9400, "lon": -102.1004, "city": "Midland",         "address": "2811 LaForce Blvd., Midland, TX 79706"},
    19: {"lat": 31.7714, "lon": -106.3811, "city": "El Paso",         "address": "6611 Boeing Drive, El Paso, TX 79925"},
    20: {"lat": 29.4474, "lon": -98.4645, "city": "San Antonio",      "address": "1314 Hines Avenue, San Antonio, TX 78208"},
}


def main():
    db = SyncSessionLocal()
    orgs_updated = 0
    jobs_reset = 0

    try:
        # Fix TEA HQ
        tea_orgs = db.query(Organization).filter(
            Organization.org_type == "state_agency"
        ).all()

        for org in tea_orgs:
            if "texas education agency" in org.name.lower():
                org.latitude = TEA_HQ["latitude"]
                org.longitude = TEA_HQ["longitude"]
                org.city = TEA_HQ["city"]
                org.city_source = "manual"
                orgs_updated += 1
                print(f"  Updated TEA HQ: {org.name} -> ({TEA_HQ['latitude']}, {TEA_HQ['longitude']})")

                # Reset jobs from this org for re-geocoding
                count = db.query(JobPosting).filter(
                    JobPosting.organization_id == org.id,
                    JobPosting.geocode_status == "success",
                ).update({
                    "geocode_status": "pending",
                    "geocode_source": None,
                }, synchronize_session=False)
                jobs_reset += count

        # Fix ESC offices
        esc_orgs = db.query(Organization).filter(
            Organization.org_type == "esc"
        ).all()

        for org in esc_orgs:
            region = org.esc_region
            if region and region in ESC_OFFICES:
                esc = ESC_OFFICES[region]
                old_lat = org.latitude
                old_lon = org.longitude
                org.latitude = esc["lat"]
                org.longitude = esc["lon"]
                org.city = esc["city"]
                org.city_source = "manual"
                orgs_updated += 1
                print(
                    f"  Updated ESC {region}: {org.name} "
                    f"({old_lat}, {old_lon}) -> ({esc['lat']}, {esc['lon']})"
                )

                # Reset jobs from this org for re-geocoding
                count = db.query(JobPosting).filter(
                    JobPosting.organization_id == org.id,
                    JobPosting.geocode_status == "success",
                ).update({
                    "geocode_status": "pending",
                    "geocode_source": None,
                }, synchronize_session=False)
                jobs_reset += count

        db.commit()
        print(f"\nDone: {orgs_updated} orgs updated, {jobs_reset} jobs reset for re-geocoding")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()
