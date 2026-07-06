"""
utils/security.py
Lightweight, dependency-free security helpers:
  - CSRF token generation/validation (session-bound, double-submit style)
  - admin login_required decorator
  - request metadata extraction (IP / browser / device) for audit trails
"""

import secrets
from functools import wraps

from flask import session, request, abort, redirect, url_for, flash


def generate_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def validate_csrf_token(submitted_token):
    real_token = session.get("csrf_token")
    return bool(real_token) and bool(submitted_token) and secrets.compare_digest(real_token, submitted_token)


def csrf_protect():
    """Call at the top of any state-changing (POST/PUT/DELETE) view."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not validate_csrf_token(token):
            abort(400, description="Invalid or missing CSRF token.")


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)
    return wrapped


def get_client_ip():
    # Respect X-Forwarded-For when behind a reverse proxy (PythonAnywhere/Nginx),
    # falling back to remote_addr for local/dev runs.
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


_BROWSER_SIGNATURES = [
    ("Edg/", "Microsoft Edge"),
    ("OPR/", "Opera"),
    ("Chrome/", "Chrome"),
    ("CriOS/", "Chrome (iOS)"),
    ("Firefox/", "Firefox"),
    ("FxiOS/", "Firefox (iOS)"),
    ("Safari/", "Safari"),
]


def get_browser_and_device():
    """Lightweight User-Agent parsing without an external dependency.
    Good enough for audit-log display purposes (not a security control)."""
    ua_string = request.headers.get("User-Agent", "") or ""

    browser = "Unknown"
    for signature, name in _BROWSER_SIGNATURES:
        if signature in ua_string:
            browser = name
            break

    ua_lower = ua_string.lower()
    if "mobile" in ua_lower or "android" in ua_lower or "iphone" in ua_lower:
        device = "Mobile"
    elif "ipad" in ua_lower or "tablet" in ua_lower:
        device = "Tablet"
    elif ua_string:
        device = "Desktop"
    else:
        device = "Unknown"

    return browser, device
