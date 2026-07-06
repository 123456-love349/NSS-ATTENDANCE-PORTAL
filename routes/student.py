"""
routes/student.py
Public-facing student attendance flow.

Two entry points:
  GET  /student/attend                -> manual attendance form (event chosen from dropdown)
  GET  /student/attend/qr/<token>     -> QR-triggered attendance form (event locked to the QR)
  POST /student/attend/submit         -> shared submission handler for both

Location is mandatory: the form will not submit without latitude/longitude
present, and the server independently re-validates this and rejects the
submission if missing (defense in depth against a tampered client).
"""

import traceback

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from werkzeug.exceptions import HTTPException

from database import get_db
from utils.event_manager import get_active_events, get_event_by_qr_token, validate_qr_for_attendance, get_event
from utils.location import reverse_geocode, build_google_maps_link, is_location_suspicious
from utils.duplicate_checker import is_duplicate_submission
from utils.proxy_detector import (
    compute_rapid_submission_flag, compute_risk_score, is_high_risk, raise_alert,
    detect_same_device, detect_impossible_travel
)
from utils.security import generate_csrf_token, csrf_protect, get_client_ip, get_browser_and_device

student_bp = Blueprint("student", __name__, url_prefix="/student")


def _wants_json_response():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json


def _render_attendance_form(status_code, *, message, category, events, locked_event, form_data):
    if _wants_json_response():
        return jsonify({"success": False, "message": message, "error": "validation_error"}), status_code
    flash(message, category)
    return render_template(
        "student/attendance_form.html",
        events=events,
        locked_event=locked_event,
        form_data=form_data,
    ), status_code


@student_bp.app_context_processor
def inject_csrf():
    return {"csrf_token": generate_csrf_token}


@student_bp.route("/attend", methods=["GET"])
def attend_manual():
    db = get_db()
    events = get_active_events(db)
    if not events:
        flash("There are no active events right now. Please check back later or contact your NSS coordinator.", "warning")
    return render_template("student/attendance_form.html", events=events, locked_event=None)


@student_bp.route("/attend/qr/<token>", methods=["GET"])
def attend_qr(token):
    db = get_db()
    event = get_event_by_qr_token(db, token)
    is_valid, reason = validate_qr_for_attendance(event)
    if not is_valid:
        flash(reason, "danger")
        return render_template("student/qr_invalid.html", reason=reason), 410
    return render_template("student/attendance_form.html", events=[event], locked_event=event)


@student_bp.route("/attend/submit", methods=["POST"])
def attend_submit():
    db = None
    try:
        csrf_protect()
        db = get_db()

        student_name = request.form.get("student_name", "").strip()
        branch = request.form.get("branch", "").strip()
        section = request.form.get("section", "").strip()
        crn = request.form.get("crn", "").strip()
        urn = request.form.get("urn", "").strip()
        phone = request.form.get("phone", "").strip()
        is_volunteer = 1 if request.form.get("is_nss_volunteer") == "on" else 0

        event_id = request.form.get("event_id", type=int)
        attendance_mode = request.form.get("attendance_mode", "manual")
        qr_token = request.form.get("qr_token", "").strip() or None

        latitude = request.form.get("latitude", type=float)
        longitude = request.form.get("longitude", type=float)
        gps_accuracy = request.form.get("gps_accuracy", type=float)
        location_timestamp = request.form.get("location_timestamp", "").strip() or None
        location_denied = request.form.get("location_denied") == "1"

        # ---- Server-side validation -------------------------------------
        errors = []
        if not student_name:
            errors.append("Full name is required.")
        if not crn and not urn:
            errors.append("At least one of CRN or URN is required.")
        if not phone:
            errors.append("Phone number is required.")
        if not event_id:
            errors.append("Please select an event.")

        if latitude is None or longitude is None:
            errors.append("Location could not be captured. Attendance cannot be recorded without location access.")

        event = get_event(db, event_id) if event_id else None
        if event is None:
            errors.append("The selected event does not exist.")
        elif qr_token:
            is_valid, reason = validate_qr_for_attendance(event)
            if not is_valid:
                errors.append(reason)
        elif not event["is_active"]:
            errors.append("This event is no longer active.")

        if errors:
            events = [event] if (event and qr_token) else get_active_events(db)
            return _render_attendance_form(
                400,
                message="; ".join(errors),
                category="danger",
                events=events,
                locked_event=event if qr_token else None,
                form_data=request.form,
            )

        # ---- Location enrichment ------------------------------------------
        location_status = "captured"
        if current_app.config["MAX_ACCEPTABLE_GPS_ACCURACY_M"] and gps_accuracy:
            if gps_accuracy > current_app.config["MAX_ACCEPTABLE_GPS_ACCURACY_M"]:
                location_status = "suspicious"

        address = reverse_geocode(latitude, longitude)
        maps_link = build_google_maps_link(latitude, longitude)

        # Use the event-specific radius if set, else fallback to standard threshold
        event_radius = event.get("venue_radius") if event.get("venue_radius") is not None else current_app.config["SUSPICIOUS_DISTANCE_METERS"]
        suspicious_location = is_location_suspicious(
            latitude, longitude, event["venue_latitude"], event["venue_longitude"],
            event_radius,
        )
        if suspicious_location:
            location_status = "suspicious"

        # ---- Duplicate + proxy/risk detection -------------------------------
        duplicate = is_duplicate_submission(db, event_id, crn or None, urn or None)
        ip_address = get_client_ip()
        browser, device = get_browser_and_device()
        rapid = compute_rapid_submission_flag(db, ip_address)

        # Advanced checks
        is_same_device, device_count = detect_same_device(db, ip_address, browser, device, event_id)
        from datetime import datetime
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        is_impossible_travel, travel_speed = detect_impossible_travel(db, crn, urn, latitude, longitude, now_str)
        is_poor_accuracy = bool(gps_accuracy and gps_accuracy > current_app.config.get("MAX_ACCEPTABLE_GPS_ACCURACY_M", 200))

        risk_score = compute_risk_score(
            current_app.config,
            is_duplicate=duplicate,
            is_location_suspicious=suspicious_location,
            has_location=True,
            is_rapid_submission=rapid,
            is_same_device=is_same_device,
            is_impossible_travel=is_impossible_travel,
            is_poor_accuracy=is_poor_accuracy
        )
        proxy_suspected = is_high_risk(risk_score)

        if duplicate:
            msg = "You (or this CRN/URN) have already marked attendance for this event."
            if _wants_json_response():
                return jsonify({"success": False, "message": msg, "error": "duplicate_submission"}), 409
            flash(msg, "warning")
            events = [event] if qr_token else get_active_events(db)
            return render_template(
                "student/attendance_form.html", events=events,
                locked_event=event if qr_token else None,
                form_data=request.form,
            ), 409

        # ---- Persist ---------------------------------------------------
        cur = db.execute(
            """INSERT INTO attendance (
                    student_name, branch, section, crn, urn, phone, is_nss_volunteer,
                    attendance_mode, event_id, event_name,
                    latitude, longitude, location_address, google_maps_link, location_status,
                    gps_accuracy_m, ip_address, browser, device,
                    is_duplicate, is_proxy_suspected, risk_score, location_timestamp
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                student_name, branch, section, crn or None, urn or None, phone, is_volunteer,
                attendance_mode, event_id, event["event_name"],
                latitude, longitude, address, maps_link, location_status,
                gps_accuracy, ip_address, browser, device,
                0, 1 if proxy_suspected else 0, risk_score, location_timestamp or now_str,
            ),
        )
        db.commit()
        attendance_id = cur.lastrowid

        if proxy_suspected:
            raise_alert(db, "proxy", attendance_id,
                         f"High risk score ({risk_score}) for {student_name} on event '{event['event_name']}'.",
                         severity="high")
            db.commit()
        if suspicious_location:
            raise_alert(db, "suspicious_location", attendance_id,
                         f"Location for {student_name} is unusually far from the event venue.",
                         severity="medium")
            db.commit()
        if is_impossible_travel:
            raise_alert(db, "suspicious_location", attendance_id,
                         f"Impossible travel speed detected for {student_name}: {travel_speed:.1f} km/h.",
                         severity="high")
            db.commit()

        if _wants_json_response():
            return jsonify({
                "success": True,
                "attendance_id": attendance_id,
                "message": "Attendance recorded successfully.",
                "redirect_url": url_for("student.attend_success", attendance_id=attendance_id),
            }), 200

        return render_template("student/attendance_success.html", event=event, address=address, maps_link=maps_link)
    except HTTPException as http_exc:
        # abort(...) (e.g. csrf_protect()'s abort(400, ...)) raises an
        # HTTPException, which IS a subclass of Exception. Without this
        # dedicated branch it used to fall into the `except Exception`
        # block below and get reported to the client as a misleading
        # HTTP 500 instead of its real status code (e.g. 400 for a bad
        # CSRF token). Handle it on its own so the correct status/message
        # reaches the frontend and gets logged distinctly from real
        # unexpected server errors.
        if db is not None:
            db.rollback()
        current_app.logger.warning(
            "Attendance submission rejected (%s): %s", http_exc.code, http_exc.description
        )
        message = http_exc.description or "The request could not be processed."
        if _wants_json_response():
            return jsonify({
                "success": False,
                "message": message,
                "error": "bad_request",
            }), http_exc.code or 400
        flash(message, "danger")
        events = get_active_events(get_db())
        return render_template(
            "student/attendance_form.html", events=events, locked_event=None, form_data=request.form
        ), http_exc.code or 400
    except Exception as exc:
        if db is not None:
            db.rollback()
        # Full traceback always goes to the server log/console so the real
        # cause is visible instead of a bare "500 Internal Server Error".
        current_app.logger.exception("Attendance submission failed")
        print(traceback.format_exc())
        if _wants_json_response():
            return jsonify({
                "success": False,
                "message": "Attendance could not be saved. Please try again.",
                "error": str(exc),
            }), 500
        flash("Attendance could not be saved. Please try again.", "danger")
        events = get_active_events(get_db())
        return render_template("student/attendance_form.html", events=events, locked_event=None, form_data=request.form), 500


@student_bp.route("/attend/success/<int:attendance_id>", methods=["GET"])
def attend_success(attendance_id):
    db = get_db()
    attendance_record = db.execute("SELECT * FROM attendance WHERE id = ?", (attendance_id,)).fetchone()
    if attendance_record is None:
        flash("The attendance record could not be found.", "warning")
        return redirect(url_for("student.attend_manual"))
    event = get_event(db, attendance_record["event_id"])
    return render_template(
        "student/attendance_success.html",
        event=event,
        address=attendance_record["location_address"],
        maps_link=attendance_record["google_maps_link"],
    )
