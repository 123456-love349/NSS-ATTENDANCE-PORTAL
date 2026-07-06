-- =====================================================================
-- NSS Attendance Management System - Database Schema (SQLite)
-- Normalized, indexed, production-ready schema.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- Admins
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admins (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    full_name       TEXT,
    email           TEXT,
    role            TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('admin', 'superadmin')),
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- OTP verification (login 2FA / student verification)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS otp_codes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier      TEXT NOT NULL,          -- username or phone/email
    purpose         TEXT NOT NULL,          -- 'admin_login' | 'student_verify'
    otp_hash        TEXT NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    is_used         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_otp_identifier ON otp_codes(identifier, purpose);

-- ---------------------------------------------------------------------
-- Events
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name          TEXT NOT NULL,
    description         TEXT,
    event_date          TEXT NOT NULL,
    venue_address       TEXT,
    venue_latitude      REAL,
    venue_longitude     REAL,
    is_active           INTEGER NOT NULL DEFAULT 0,
    qr_token            TEXT UNIQUE,
    qr_generated_at     TEXT,
    qr_expires_at       TEXT,
    qr_image_path       TEXT,
    created_by          INTEGER REFERENCES admins(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_active ON events(is_active);
CREATE INDEX IF NOT EXISTS idx_events_qr_token ON events(qr_token);

-- ---------------------------------------------------------------------
-- Students (master roster - used for duplicate/roster cross-checks)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS students (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    student_name        TEXT NOT NULL,
    branch              TEXT,
    section             TEXT,
    crn                 TEXT UNIQUE,
    urn                 TEXT UNIQUE,
    phone               TEXT,
    is_nss_volunteer    INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_students_crn ON students(crn);
CREATE INDEX IF NOT EXISTS idx_students_urn ON students(urn);
CREATE INDEX IF NOT EXISTS idx_students_name ON students(student_name);

-- ---------------------------------------------------------------------
-- OCR uploads / batch jobs (created before attendance since attendance
-- has a nullable FK back to it)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ocr_uploads (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    original_filename   TEXT NOT NULL,
    stored_filename     TEXT NOT NULL,
    file_type           TEXT NOT NULL,
    event_id            INTEGER REFERENCES events(id),
    uploaded_by         INTEGER REFERENCES admins(id),
    total_rows_detected INTEGER NOT NULL DEFAULT 0,
    total_duplicates    INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'processing' CHECK (
                            status IN ('processing', 'completed', 'failed')
                         ),
    report_path         TEXT,
    error_message       TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- Attendance (the core transactional table)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attendance (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    student_name        TEXT NOT NULL,
    branch              TEXT,
    section             TEXT,
    crn                 TEXT,
    urn                 TEXT,
    phone               TEXT,
    is_nss_volunteer    INTEGER NOT NULL DEFAULT 0,

    attendance_mode     TEXT NOT NULL CHECK (attendance_mode IN ('manual', 'qr', 'ocr')),

    event_id            INTEGER REFERENCES events(id),
    event_name          TEXT,

    latitude            REAL,
    longitude           REAL,
    location_address    TEXT,
    google_maps_link    TEXT,
    location_timestamp  TEXT,
    location_status     TEXT NOT NULL DEFAULT 'captured' CHECK (
                            location_status IN ('captured', 'denied', 'unavailable', 'suspicious')
                         ),
    gps_accuracy_m      REAL,

    ip_address          TEXT,
    browser             TEXT,
    device              TEXT,

    is_duplicate        INTEGER NOT NULL DEFAULT 0,
    is_proxy_suspected  INTEGER NOT NULL DEFAULT 0,
    risk_score          INTEGER NOT NULL DEFAULT 0,

    ocr_upload_id       INTEGER REFERENCES ocr_uploads(id),

    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_attendance_event ON attendance(event_id);
CREATE INDEX IF NOT EXISTS idx_attendance_crn ON attendance(crn);
CREATE INDEX IF NOT EXISTS idx_attendance_urn ON attendance(urn);
CREATE INDEX IF NOT EXISTS idx_attendance_created ON attendance(created_at);
CREATE INDEX IF NOT EXISTS idx_attendance_branch ON attendance(branch);
CREATE INDEX IF NOT EXISTS idx_attendance_duplicate ON attendance(is_duplicate);
CREATE INDEX IF NOT EXISTS idx_attendance_proxy ON attendance(is_proxy_suspected);

-- ---------------------------------------------------------------------
-- OCR extracted rows (raw extraction results, before/after DB cross-check)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ocr_extracted_rows (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ocr_upload_id       INTEGER NOT NULL REFERENCES ocr_uploads(id) ON DELETE CASCADE,
    raw_text            TEXT,
    extracted_name      TEXT,
    extracted_crn       TEXT,
    extracted_urn       TEXT,
    extracted_phone     TEXT,
    confidence          REAL,
    is_duplicate_in_db  INTEGER NOT NULL DEFAULT 0,
    matched_student_id  INTEGER REFERENCES students(id),
    accepted            INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ocr_rows_upload ON ocr_extracted_rows(ocr_upload_id);

-- ---------------------------------------------------------------------
-- AI Alerts (surfaced on dashboard)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai_alerts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type          TEXT NOT NULL CHECK (
                            alert_type IN ('duplicate', 'proxy', 'suspicious_location', 'high_risk')
                         ),
    attendance_id       INTEGER REFERENCES attendance(id) ON DELETE CASCADE,
    message             TEXT NOT NULL,
    severity            TEXT NOT NULL DEFAULT 'medium' CHECK (severity IN ('low', 'medium', 'high')),
    is_resolved         INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON ai_alerts(is_resolved);

-- ---------------------------------------------------------------------
-- Audit log (security: track admin actions)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id            INTEGER REFERENCES admins(id),
    action              TEXT NOT NULL,
    details             TEXT,
    ip_address          TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
