"""
One-time migration: move player_document_blobs from Postgres → Supabase Storage.

Usage:
    # Preview what would be migrated (no changes made)
    DATABASE_URL=... SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python scripts/migrate_blobs_to_storage.py --dry-run

    # Run the actual migration
    DATABASE_URL=... SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python scripts/migrate_blobs_to_storage.py

After confirming all downloads work, free the DB space by running this in
the Supabase SQL editor:
    TRUNCATE player_document_blobs;
"""

import os
import sys
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("migrate")

# Allow imports from the src/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def migrate(dry_run: bool = False) -> None:
    database_url = os.environ.get("DATABASE_URL")
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not database_url:
        log.error("DATABASE_URL environment variable is not set.")
        sys.exit(1)
    if not supabase_url or not supabase_key:
        log.error("SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables must be set.")
        sys.exit(1)

    if dry_run:
        log.info("=== DRY RUN — no changes will be made ===")

    from database import PlayerDB
    from supabase_storage import upload_file as storage_upload

    db = PlayerDB(database_url=database_url)

    if not db.is_postgres:
        log.error("This migration targets the Postgres (Supabase) database. "
                  "DATABASE_URL does not appear to point to Postgres.")
        db.close()
        sys.exit(1)

    cursor = db.conn.cursor()

    # Count total blobs to migrate
    db._execute(cursor, "SELECT COUNT(*) as total FROM player_document_blobs")
    count_row = cursor.fetchone()
    total = count_row["total"] if hasattr(count_row, "keys") else count_row[0]
    log.info(f"Found {total} blob(s) to migrate.")

    if total == 0:
        log.info("Nothing to migrate. Exiting.")
        db.close()
        return

    # Fetch all blob rows (doc_id + data + content_type)
    db._execute(cursor, "SELECT doc_id, content_type, data FROM player_document_blobs ORDER BY doc_id")
    rows = cursor.fetchall()

    migrated = 0
    skipped = 0
    failed = 0

    for row in rows:
        row = dict(row)
        doc_id = row["doc_id"]
        content_type = row["content_type"] or "application/pdf"
        data = bytes(row["data"]) if row["data"] else None

        if not data:
            log.warning(f"  doc_id={doc_id}: empty blob, skipping.")
            skipped += 1
            continue

        log.info(f"  doc_id={doc_id}: {len(data):,} bytes ({content_type})")

        if dry_run:
            migrated += 1
            continue

        try:
            # Upload to Supabase Storage
            storage_path = storage_upload(doc_id, data, content_type)

            # Record the storage path in player_documents
            db.set_document_storage_path(doc_id, storage_path)

            # Remove the blob row now that it's safely in Storage
            db._execute(cursor, "DELETE FROM player_document_blobs WHERE doc_id = %s", (doc_id,))
            db.conn.commit()

            log.info(f"  doc_id={doc_id}: migrated → {storage_path}")
            migrated += 1

        except Exception as exc:
            log.error(f"  doc_id={doc_id}: FAILED — {exc}")
            failed += 1

    db.close()

    log.info("=" * 50)
    if dry_run:
        log.info(f"DRY RUN complete. Would have migrated {migrated} blob(s), skipped {skipped}.")
    else:
        log.info(f"Migration complete. Migrated: {migrated}, Skipped: {skipped}, Failed: {failed}.")
        if failed:
            log.warning(f"{failed} blob(s) failed — review errors above before truncating the table.")
        else:
            log.info("All blobs migrated successfully.")
            log.info("When you're ready to free the DB space, run this in the Supabase SQL editor:")
            log.info("    TRUNCATE player_document_blobs;")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate player document blobs to Supabase Storage.")
    parser.add_argument("--dry-run", action="store_true", help="Preview migration without making changes.")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
