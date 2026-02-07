#!/usr/bin/env python3
"""Seed district demographics from TEA SQLite into PostgreSQL.

Run inside Docker:
    docker compose exec backend python scripts/seed_demographics.py

Or locally with the right DATABASE_URL:
    cd backend && python ../scripts/seed_demographics.py
"""

import sqlite3
import sys
import uuid
from pathlib import Path

# Add backend to path for imports
# In Docker: script is at /app/scripts/, backend code is at /app/
# Locally: script is at scripts/, backend code is at backend/
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
backend_dir = project_root / "backend"
if backend_dir.exists():
    sys.path.insert(0, str(backend_dir))
else:
    # Inside Docker, /app is the backend root
    sys.path.insert(0, str(script_dir.parent))

from sqlalchemy import text
from app.models.base import sync_engine, SyncSessionLocal

TEA_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "tea_data.db"
# In Docker, the path is different
if not TEA_DB_PATH.exists():
    TEA_DB_PATH = Path("/app/data/tea_data.db")


def main():
    if not TEA_DB_PATH.exists():
        print(f"TEA DB not found at {TEA_DB_PATH}")
        sys.exit(1)

    # Read TEA data
    conn = sqlite3.connect(TEA_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("""
        SELECT
            d.tea_id,
            a.school_year,
            a.total_students,
            a.economically_disadvantaged,
            a.at_risk,
            a.ell,
            a.special_ed,
            a.gifted_talented,
            a.homeless,
            a.foster_care,
            a.economically_disadvantaged_count,
            a.at_risk_count,
            a.ell_count,
            a.special_ed_count,
            a.gifted_talented_count,
            a.homeless_count,
            a.foster_care_count,
            a.bilingual_count,
            a.esl_count,
            a.dyslexic_count,
            a.military_connected_count,
            a.section_504_count,
            a.title_i_count,
            a.migrant_count
        FROM arc_factors a
        JOIN districts d ON a.district_id = d.id
    """)
    tea_rows = cursor.fetchall()
    conn.close()
    print(f"Read {len(tea_rows)} rows from TEA SQLite")

    # Look up organization_id by tea_id in PostgreSQL
    session = SyncSessionLocal()
    try:
        result = session.execute(text("SELECT id, tea_id FROM organizations WHERE tea_id IS NOT NULL"))
        org_map = {row.tea_id: row.id for row in result}
        print(f"Found {len(org_map)} organizations with tea_id")

        inserted = 0
        skipped = 0
        for row in tea_rows:
            tea_id = row["tea_id"]
            org_id = org_map.get(tea_id)
            if not org_id:
                skipped += 1
                continue

            # Upsert using INSERT ON CONFLICT
            session.execute(text("""
                INSERT INTO district_demographics (
                    id, organization_id, school_year, total_students,
                    economically_disadvantaged, at_risk, ell, special_ed,
                    gifted_talented, homeless, foster_care,
                    economically_disadvantaged_count, at_risk_count, ell_count,
                    special_ed_count, gifted_talented_count, homeless_count,
                    foster_care_count, bilingual_count, esl_count, dyslexic_count,
                    military_connected_count, section_504_count, title_i_count,
                    migrant_count, created_at, updated_at
                ) VALUES (
                    :id, :organization_id, :school_year, :total_students,
                    :economically_disadvantaged, :at_risk, :ell, :special_ed,
                    :gifted_talented, :homeless, :foster_care,
                    :economically_disadvantaged_count, :at_risk_count, :ell_count,
                    :special_ed_count, :gifted_talented_count, :homeless_count,
                    :foster_care_count, :bilingual_count, :esl_count, :dyslexic_count,
                    :military_connected_count, :section_504_count, :title_i_count,
                    :migrant_count, NOW(), NOW()
                )
                ON CONFLICT (organization_id, school_year) DO UPDATE SET
                    total_students = EXCLUDED.total_students,
                    economically_disadvantaged = EXCLUDED.economically_disadvantaged,
                    at_risk = EXCLUDED.at_risk,
                    ell = EXCLUDED.ell,
                    special_ed = EXCLUDED.special_ed,
                    gifted_talented = EXCLUDED.gifted_talented,
                    homeless = EXCLUDED.homeless,
                    foster_care = EXCLUDED.foster_care,
                    economically_disadvantaged_count = EXCLUDED.economically_disadvantaged_count,
                    at_risk_count = EXCLUDED.at_risk_count,
                    ell_count = EXCLUDED.ell_count,
                    special_ed_count = EXCLUDED.special_ed_count,
                    gifted_talented_count = EXCLUDED.gifted_talented_count,
                    homeless_count = EXCLUDED.homeless_count,
                    foster_care_count = EXCLUDED.foster_care_count,
                    bilingual_count = EXCLUDED.bilingual_count,
                    esl_count = EXCLUDED.esl_count,
                    dyslexic_count = EXCLUDED.dyslexic_count,
                    military_connected_count = EXCLUDED.military_connected_count,
                    section_504_count = EXCLUDED.section_504_count,
                    title_i_count = EXCLUDED.title_i_count,
                    migrant_count = EXCLUDED.migrant_count,
                    updated_at = NOW()
            """), {
                "id": str(uuid.uuid4()),
                "organization_id": str(org_id),
                "school_year": row["school_year"],
                "total_students": row["total_students"],
                "economically_disadvantaged": row["economically_disadvantaged"],
                "at_risk": row["at_risk"],
                "ell": row["ell"],
                "special_ed": row["special_ed"],
                "gifted_talented": row["gifted_talented"],
                "homeless": row["homeless"],
                "foster_care": row["foster_care"],
                "economically_disadvantaged_count": row["economically_disadvantaged_count"],
                "at_risk_count": row["at_risk_count"],
                "ell_count": row["ell_count"],
                "special_ed_count": row["special_ed_count"],
                "gifted_talented_count": row["gifted_talented_count"],
                "homeless_count": row["homeless_count"],
                "foster_care_count": row["foster_care_count"],
                "bilingual_count": row["bilingual_count"],
                "esl_count": row["esl_count"],
                "dyslexic_count": row["dyslexic_count"],
                "military_connected_count": row["military_connected_count"],
                "section_504_count": row["section_504_count"],
                "title_i_count": row["title_i_count"],
                "migrant_count": row["migrant_count"],
            })
            inserted += 1

        session.commit()
        print(f"\nInserted/updated: {inserted}")
        print(f"Skipped (no matching org): {skipped}")

    finally:
        session.close()


if __name__ == "__main__":
    main()
