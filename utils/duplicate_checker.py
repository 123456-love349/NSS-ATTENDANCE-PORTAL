"""
utils/duplicate_checker.py
Detects duplicate attendance submissions for the same event.

A submission is considered a duplicate if the same CRN or URN (whichever is
provided) already has an attendance record for the same event_id. This
runs at submission time (to warn/block) and can also be re-run in batch
from the admin dashboard.
"""


def find_existing_attendance(db, event_id, crn, urn):
    """Return the existing attendance row (sqlite3.Row) for this
    event+student if one exists, else None."""
    if not event_id:
        return None

    if crn:
        row = db.execute(
            "SELECT * FROM attendance WHERE event_id = ? AND crn = ? LIMIT 1",
            (event_id, crn),
        ).fetchone()
        if row:
            return row

    if urn:
        row = db.execute(
            "SELECT * FROM attendance WHERE event_id = ? AND urn = ? LIMIT 1",
            (event_id, urn),
        ).fetchone()
        if row:
            return row

    return None


def is_duplicate_submission(db, event_id, crn, urn):
    return find_existing_attendance(db, event_id, crn, urn) is not None


def get_all_duplicates(db):
    """Return all attendance rows flagged as duplicates, most recent first."""
    return db.execute(
        """SELECT * FROM attendance WHERE is_duplicate = 1
           ORDER BY created_at DESC"""
    ).fetchall()
