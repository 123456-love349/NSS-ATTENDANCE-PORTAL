"""
utils/event_manager.py
Business logic for event CRUD + QR lifecycle, kept separate from the
routes/admin.py view functions so it's independently testable/reusable.
"""

from datetime import datetime

from utils.qr_generator import generate_qr_token, generate_qr_image, compute_expiry, is_qr_expired


def create_event(db, *, event_name, description, event_date, venue_address,
                  venue_latitude, venue_longitude, venue_radius=100.0, created_by):
    cur = db.execute(
        """INSERT INTO events (event_name, description, event_date, venue_address,
                                venue_latitude, venue_longitude, venue_radius, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_name, description, event_date, venue_address,
         venue_latitude, venue_longitude, venue_radius, created_by),
    )
    db.commit()
    return cur.lastrowid


def update_event(db, event_id, **fields):
    if not fields:
        return
    allowed = {"event_name", "description", "event_date", "venue_address",
               "venue_latitude", "venue_longitude", "venue_radius"}
    set_clause = ", ".join(f"{k} = ?" for k in fields if k in allowed)
    values = [v for k, v in fields.items() if k in allowed]
    if not set_clause:
        return
    values.append(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    values.append(event_id)
    db.execute(
        f"UPDATE events SET {set_clause}, updated_at = ? WHERE id = ?",
        values,
    )
    db.commit()


def delete_event(db, event_id):
    db.execute("DELETE FROM events WHERE id = ?", (event_id,))
    db.commit()


def set_event_active(db, event_id, active: bool):
    db.execute(
        "UPDATE events SET is_active = ?, updated_at = datetime('now') WHERE id = ?",
        (1 if active else 0, event_id),
    )
    db.commit()


def generate_event_qr(db, event_id, base_url, qr_folder, validity_minutes):
    token = generate_qr_token()
    full_path, filename, attend_url = generate_qr_image(token, base_url, qr_folder)
    expires_at = compute_expiry(validity_minutes)

    db.execute(
        """UPDATE events
           SET qr_token = ?, qr_generated_at = datetime('now'),
               qr_expires_at = ?, qr_image_path = ?, updated_at = datetime('now')
           WHERE id = ?""",
        (token, expires_at.isoformat(), filename, event_id),
    )
    db.commit()
    return {"token": token, "filename": filename, "attend_url": attend_url,
            "expires_at": expires_at}


def get_event_by_qr_token(db, token):
    return db.execute("SELECT * FROM events WHERE qr_token = ?", (token,)).fetchone()


def validate_qr_for_attendance(event_row):
    """Returns (is_valid: bool, reason: str|None)."""
    if event_row is None:
        return False, "Invalid QR code."
    if not event_row["is_active"]:
        return False, "This event is not currently active."
    if is_qr_expired(event_row["qr_expires_at"]):
        return False, "This QR code has expired. Please ask the organizer to regenerate it."
    return True, None


def get_all_events(db):
    return db.execute("SELECT * FROM events ORDER BY event_date DESC, id DESC").fetchall()


def get_active_events(db):
    return db.execute(
        "SELECT * FROM events WHERE is_active = 1 ORDER BY event_date DESC"
    ).fetchall()


def get_event(db, event_id):
    return db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
