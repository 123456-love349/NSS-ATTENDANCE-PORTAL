"""
config.py
Central configuration for the NSS Attendance Management System.

Design goals:
- Zero code changes required between Windows / Linux / PythonAnywhere.
- All paths are computed relative to this file's location (BASE_DIR),
  never hard-coded absolute paths, so the project can be dropped into
  any directory (including a PythonAnywhere home directory) and just work.
- All secrets/tunables are read from environment variables with safe
  defaults, so a plain `python app.py` works out of the box for local
  development/testing, while production deployments can override via
  a `.env` file or PythonAnywhere's "Environment variables" panel.
"""

import os
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Config:
    # ------------------------------------------------------------------
    # Core Flask
    # ------------------------------------------------------------------
    SECRET_KEY = os.environ.get("NSS_SECRET_KEY", "dev-insecure-secret-key-change-me")
    DEBUG = _env_bool("NSS_DEBUG", False)
    TESTING = False

    # ------------------------------------------------------------------
    # Paths (all relative to BASE_DIR -> portable across OS/hosts)
    # ------------------------------------------------------------------
    DATABASE_DIR = os.path.join(BASE_DIR, "database")
    DATABASE_PATH = os.path.join(DATABASE_DIR, "nss_attendance.db")
    SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    QR_FOLDER = os.path.join(BASE_DIR, "static", "qrcodes")
    EXCEL_EXPORT_FOLDER = os.path.join(BASE_DIR, "excel_reports")
    OCR_REPORT_FOLDER = os.path.join(BASE_DIR, "excel_reports", "ocr_reports")

    ALLOWED_OCR_EXTENSIONS = {"png", "jpg", "jpeg", "bmp", "tiff", "pdf", "xlsx", "xls", "csv"}
    ALLOWED_IMPORT_EXTENSIONS = {"xlsx", "xls", "csv"}
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB upload cap

    # ------------------------------------------------------------------
    # Session / auth
    # ------------------------------------------------------------------
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Set NSS_FORCE_SECURE_COOKIES=1 once served over HTTPS (PythonAnywhere free
    # tier terminates TLS at the proxy, so this is opt-in rather than forced).
    SESSION_COOKIE_SECURE = _env_bool("NSS_FORCE_SECURE_COOKIES", False)

    # Default admin bootstrap credentials (only used the first time the DB is
    # created; change immediately after first login).
    DEFAULT_ADMIN_USERNAME = os.environ.get("NSS_ADMIN_USER", "admin")
    DEFAULT_ADMIN_PASSWORD = os.environ.get("NSS_ADMIN_PASSWORD", "LoveMe@123")

    # ------------------------------------------------------------------
    # QR attendance
    # ------------------------------------------------------------------
    QR_DEFAULT_VALIDITY_MINUTES = 15

    # ------------------------------------------------------------------
    # Location / anti-proxy
    # ------------------------------------------------------------------
    # Reject attendance if the reported GPS accuracy radius (meters) is worse
    # than this, to reduce spoofed/low-quality location proxying.
    MAX_ACCEPTABLE_GPS_ACCURACY_M = 200
    # Flag as "suspicious location" if a student's attendance for the same
    # event is geographically farther apart than this from the event's
    # designated location (if one is set).
    SUSPICIOUS_DISTANCE_METERS = 500
    GEOCODER_USER_AGENT = "nss-attendance-system"

    # ------------------------------------------------------------------
    # Risk scoring weights (AI Alerts)
    # ------------------------------------------------------------------
    RISK_WEIGHT_DUPLICATE = 40
    RISK_WEIGHT_PROXY_LOCATION = 30
    RISK_WEIGHT_NO_LOCATION = 20
    RISK_WEIGHT_RAPID_SUBMISSION = 10


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


def get_config():
    env = os.environ.get("NSS_ENV", "production").lower()
    if env == "development":
        return DevelopmentConfig
    return ProductionConfig
