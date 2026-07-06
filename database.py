"""
database.py
SQLite connection management and schema bootstrap.

Uses Flask's application context (`g`) to keep one connection per request,
a dict-based row_factory so callers can access columns both by name
(dict-like, including `.get("col")` with a default) and via `row["col"]`
subscripting, and foreign_keys pragma enabled per-connection (SQLite does
not turn this on by default).

NOTE ON ROW FACTORY:
sqlite3's built-in `sqlite3.Row` supports `row["col"]` but *not* `row.get(...)`
(it is not a dict, only dict-*like*). Several call sites across this codebase
(routes/student.py's attendance-submit flow, utils/excel_exporter.py,
utils/pdf_generator.py, utils/ocr_helper.py) call `.get("col")` /
`.get("col", default)` on rows returned from `get_db()`, which raises
`AttributeError: 'sqlite3.Row' object has no attribute 'get'` and previously
produced HTTP 500s (most notably on every attendance submission, since
`attend_submit()` calls `event.get("venue_radius")`). Using a plain-dict
row factory instead keeps `row["col"]` working exactly as before while also
making `.get()` work everywhere, without having to touch every call site.
"""

import os
import sqlite3

from flask import current_app, g
from werkzeug.security import generate_password_hash


def _dict_row_factory(cursor, row):
    """Row factory that returns plain dicts instead of sqlite3.Row.

    Plain dicts support both `row["col"]` and `row.get("col", default)`,
    are natively JSON-serializable (handy if a route ever jsonifies a row
    directly), and are drop-in compatible with `dict(row)` conversions
    already used elsewhere in the codebase.
    """
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def get_db():
    """Return a request-scoped SQLite connection."""
    if "db" not in g:
        db_path = current_app.config["DATABASE_PATH"]
        g.db = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = _dict_row_factory
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    """Create the database file + tables if they don't exist yet, and seed
    a default admin account. Safe to call on every startup (idempotent)."""
    os.makedirs(app.config["DATABASE_DIR"], exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["QR_FOLDER"], exist_ok=True)
    os.makedirs(app.config["EXCEL_EXPORT_FOLDER"], exist_ok=True)
    os.makedirs(app.config["OCR_REPORT_FOLDER"], exist_ok=True)

    db_path = app.config["DATABASE_PATH"]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    with open(app.config["SCHEMA_PATH"], "r", encoding="utf-8") as f:
        conn.executescript(f.read())

    # Run migrations to dynamically add new columns
    run_migrations(conn)

    # Seed or refresh the default admin account so login works with the
    # configured defaults even when the database already exists.
    existing_admin = conn.execute(
        "SELECT id FROM admins WHERE username = ?",
        (app.config["DEFAULT_ADMIN_USERNAME"],),
    ).fetchone()

    password_hash = generate_password_hash(app.config["DEFAULT_ADMIN_PASSWORD"])

    if existing_admin is None:
        conn.execute(
            """INSERT INTO admins (username, password_hash, full_name, role, is_active)
               VALUES (?, ?, ?, 'superadmin', 1)""",
            (
                app.config["DEFAULT_ADMIN_USERNAME"],
                password_hash,
                "System Administrator",
            ),
        )
    else:
        conn.execute(
            """UPDATE admins
               SET password_hash = ?,
                   full_name = ?,
                   role = 'superadmin',
                   is_active = 1,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (
                password_hash,
                "System Administrator",
                existing_admin["id"],
            ),
        )

    conn.commit()

    conn.close()


def run_migrations(conn):
    """Dynamically add new columns to existing tables if not present (SQLite safe migration)."""
    # Migration 1: Add venue_radius to events
    cursor = conn.execute("PRAGMA table_info(events)")
    event_cols = [row["name"] for row in cursor.fetchall()]
    if "venue_radius" not in event_cols:
        conn.execute("ALTER TABLE events ADD COLUMN venue_radius REAL DEFAULT 100.0")
        conn.commit()

    # Migration 2: Add attendance columns used by the submission flow
    cursor = conn.execute("PRAGMA table_info(attendance)")
    att_cols = [row["name"] for row in cursor.fetchall()]
    for column_name, definition in [
        ("location_timestamp", "TEXT"),
        ("gps_accuracy_m", "REAL"),
        ("location_status", "TEXT NOT NULL DEFAULT 'captured'"),
        ("google_maps_link", "TEXT"),
        ("location_address", "TEXT"),
        ("latitude", "REAL"),
        ("longitude", "REAL"),
        ("browser", "TEXT"),
        ("device", "TEXT"),
        ("ip_address", "TEXT"),
        ("risk_score", "INTEGER NOT NULL DEFAULT 0"),
        ("is_proxy_suspected", "INTEGER NOT NULL DEFAULT 0"),
        ("is_duplicate", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        if column_name not in att_cols:
            conn.execute(f"ALTER TABLE attendance ADD COLUMN {column_name} {definition}")
            conn.commit()
            att_cols = [row["name"] for row in conn.execute("PRAGMA table_info(attendance)").fetchall()]


def register_db(app):
    """Wire up teardown handler so connections close after each request."""
    app.teardown_appcontext(close_db)
