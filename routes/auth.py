"""
routes/auth.py
Admin authentication: username/password.

Flow:
  GET  /auth/login   -> render login form
  POST /auth/login   -> verify username/password, establish session, redirect to dashboard
  POST /auth/logout  -> clear session
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash

from database import get_db
from utils.security import generate_csrf_token, csrf_protect, get_client_ip

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.app_context_processor
def inject_csrf():
    return {"csrf_token": generate_csrf_token}


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_id"):
        return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        csrf_protect()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        admin = db.execute(
            "SELECT * FROM admins WHERE username = ? AND is_active = 1", (username,)
        ).fetchone()

        if admin is None or not check_password_hash(admin["password_hash"], password):
            flash("Invalid username or password.", "danger")
            return render_template("auth/login.html"), 401

        session.clear()
        session["admin_id"] = admin["id"]
        session["admin_username"] = username
        session.permanent = True

        db.execute(
            "INSERT INTO audit_log (admin_id, action, details, ip_address) VALUES (?, 'login', 'Admin logged in', ?)",
            (admin["id"], get_client_ip()),
        )
        db.commit()

        flash("Login successful.", "success")
        return redirect(url_for("admin.dashboard"))

    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    admin_id = session.get("admin_id")
    if admin_id:
        db = get_db()
        db.execute(
            "INSERT INTO audit_log (admin_id, action, details, ip_address) VALUES (?, 'logout', 'Admin logged out', ?)",
            (admin_id, get_client_ip()),
        )
        db.commit()
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
