"""
utils/qr_generator.py
Generates and validates event QR codes.

Each event gets a unique random token embedded into a URL
(`/student/attend/qr/<token>`). The QR image encodes that URL. Expiry is
enforced server-side (qr_expires_at column) rather than relying on the QR
image itself, so admins can also manually deactivate/expire a code early.
"""

import os
import secrets
from datetime import datetime, timedelta

import qrcode


def generate_qr_token():
    """Cryptographically random, URL-safe token identifying one QR code."""
    return secrets.token_urlsafe(24)


def generate_qr_image(token, base_url, qr_folder):
    """Create a QR PNG encoding the attendance URL for this token.

    Returns the relative path (under static/) so templates can render it
    directly via url_for('static', filename=...).
    """
    os.makedirs(qr_folder, exist_ok=True)
    attend_url = f"{base_url.rstrip('/')}/student/attend/qr/{token}"

    img = qrcode.make(attend_url)
    filename = f"event_qr_{token}.png"
    full_path = os.path.join(qr_folder, filename)
    img.save(full_path)
    return full_path, filename, attend_url


def compute_expiry(validity_minutes):
    return datetime.utcnow() + timedelta(minutes=validity_minutes)


def is_qr_expired(qr_expires_at_str):
    """qr_expires_at_str is stored as an ISO-ish string (UTC) in SQLite."""
    if not qr_expires_at_str:
        return True
    try:
        expires_at = datetime.fromisoformat(qr_expires_at_str)
    except ValueError:
        return True
    return datetime.utcnow() > expires_at
