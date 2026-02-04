"""Generate report of districts still unmapped to a job posting platform.

Outputs a CSV sorted by enrollment (largest first) showing which districts
still need manual research to identify their job posting platform.

Usage:
    docker compose exec backend python -m scripts.discovery.report_unmapped
    docker compose exec backend python -m scripts.discovery.report_unmapped --output /app/data/unmapped.csv
"""

import argparse
import csv
import io
import logging

from app.models.base import SyncSessionLocal
from app.models.organization import Organization

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def report(output_path: str | None = None):
    db = SyncSessionLocal()
    try:
        # Overall stats
        total = db.query(Organization).filter(
            Organization.org_type.in_(["isd", "charter"]),
        ).count()

        by_status = {}
        for status in ("mapped", "probing", "unmapped", "no_online_postings"):
            count = db.query(Organization).filter(
                Organization.org_type.in_(["isd", "charter"]),
                Organization.platform_status == status,
            ).count()
            by_status[status] = count

        print(f"\n=== Platform Mapping Status ===")
        print(f"Total TEA districts: {total}")
        for status, count in by_status.items():
            pct = (count / total * 100) if total else 0
            print(f"  {status}: {count} ({pct:.1f}%)")

        # Get unmapped districts
        unmapped = db.query(Organization).filter(
            Organization.org_type.in_(["isd", "charter"]),
            Organization.platform_status.in_(["unmapped", "probing"]),
        ).order_by(
            Organization.total_students.desc().nullslast(),
        ).all()

        print(f"\n=== Unmapped Districts ({len(unmapped)}) ===")
        print(f"Sorted by enrollment (largest first)\n")

        # Write CSV
        if output_path:
            f = open(output_path, "w", newline="")
        else:
            f = io.StringIO()

        writer = csv.writer(f)
        writer.writerow(["tea_id", "name", "org_type", "esc_region", "county", "total_students", "platform_status"])

        for org in unmapped:
            writer.writerow([
                org.tea_id,
                org.name,
                org.org_type,
                org.esc_region,
                org.county,
                org.total_students or "",
                org.platform_status,
            ])

        if output_path:
            f.close()
            print(f"CSV written to {output_path}")
        else:
            # Print to stdout
            if isinstance(f, io.StringIO):
                print(f.getvalue())

        # Show top 20 by enrollment
        print("\n--- Top 20 Unmapped by Enrollment ---")
        for org in unmapped[:20]:
            students = f"{org.total_students:,}" if org.total_students else "N/A"
            print(f"  {org.tea_id}  {org.name:<45} Region {org.esc_region or '?':>2}  {students:>8} students")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Report unmapped districts")
    parser.add_argument("--output", "-o", help="Output CSV path (default: stdout)")
    args = parser.parse_args()
    report(output_path=args.output)
