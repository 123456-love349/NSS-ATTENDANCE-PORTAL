"""
routes/admin.py
Admin-only views: dashboard, event management, attendance browsing.
All routes require an authenticated session (login_required).
"""

import os
import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_file

from database import get_db
from utils.security import login_required, generate_csrf_token, csrf_protect, get_client_ip
from utils.event_manager import (
    create_event, update_event, delete_event, set_event_active,
    generate_event_qr, get_all_events, get_event, get_active_events
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.app_context_processor
def inject_csrf():
    return {"csrf_token": generate_csrf_token}


@admin_bp.route("/dashboard")
@login_required
def dashboard():
    db = get_db()

    total_students = db.execute("SELECT COUNT(DISTINCT COALESCE(crn, urn)) AS c FROM attendance").fetchone()["c"]
    today_attendance = db.execute(
        "SELECT COUNT(*) AS c FROM attendance WHERE date(created_at) = date('now')"
    ).fetchone()["c"]
    total_events = db.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
    total_duplicates = db.execute("SELECT COUNT(*) AS c FROM attendance WHERE is_duplicate = 1").fetchone()["c"]
    total_proxy = db.execute("SELECT COUNT(*) AS c FROM attendance WHERE is_proxy_suspected = 1").fetchone()["c"]
    total_ocr_uploads = db.execute("SELECT COUNT(*) AS c FROM ocr_uploads").fetchone()["c"]

    recent_attendance = db.execute(
        "SELECT * FROM attendance ORDER BY created_at DESC LIMIT 15"
    ).fetchall()

    branch_breakdown = db.execute(
        """SELECT COALESCE(NULLIF(branch, ''), 'Unspecified') AS branch, COUNT(*) AS c
           FROM attendance GROUP BY branch ORDER BY c DESC LIMIT 10"""
    ).fetchall()

    event_breakdown = db.execute(
        """SELECT COALESCE(NULLIF(event_name, ''), 'Unknown') AS event_name, COUNT(*) AS c
           FROM attendance GROUP BY event_name ORDER BY c DESC LIMIT 10"""
    ).fetchall()

    active_alerts = db.execute(
        "SELECT * FROM ai_alerts WHERE is_resolved = 0 ORDER BY created_at DESC LIMIT 10"
    ).fetchall()

    branch_labels = [r["branch"] for r in branch_breakdown]
    branch_counts = [r["c"] for r in branch_breakdown]

    event_labels = [r["event_name"] for r in event_breakdown]
    event_counts = [r["c"] for r in event_breakdown]

    return render_template(
        "admin/dashboard.html",
        total_students=total_students,
        today_attendance=today_attendance,
        total_events=total_events,
        total_duplicates=total_duplicates,
        total_proxy=total_proxy,
        total_ocr_uploads=total_ocr_uploads,
        recent_attendance=recent_attendance,
        branch_breakdown=branch_breakdown,
        event_breakdown=event_breakdown,
        active_alerts=active_alerts,
        branch_labels=branch_labels,
        branch_counts=branch_counts,
        event_labels=event_labels,
        event_counts=event_counts,
    )


# =========================================================================
# Event management
# =========================================================================

@admin_bp.route("/events")
@login_required
def events_list():
    db = get_db()
    events = get_all_events(db)
    return render_template("admin/events.html", events=events)


@admin_bp.route("/events/create", methods=["POST"])
@login_required
def events_create():
    csrf_protect()
    from flask import session
    db = get_db()
    create_event(
        db,
        event_name=request.form.get("event_name", "").strip(),
        description=request.form.get("description", "").strip(),
        event_date=request.form.get("event_date", "").strip(),
        venue_address=request.form.get("venue_address", "").strip(),
        venue_latitude=request.form.get("venue_latitude", type=float),
        venue_longitude=request.form.get("venue_longitude", type=float),
        venue_radius=request.form.get("venue_radius", 100.0, type=float),
        created_by=session.get("admin_id"),
    )
    flash("Event created successfully.", "success")
    return redirect(url_for("admin.events_list"))


@admin_bp.route("/events/<int:event_id>/update", methods=["POST"])
@login_required
def events_update(event_id):
    csrf_protect()
    db = get_db()
    update_event(
        db, event_id,
        event_name=request.form.get("event_name", "").strip(),
        description=request.form.get("description", "").strip(),
        event_date=request.form.get("event_date", "").strip(),
        venue_address=request.form.get("venue_address", "").strip(),
        venue_latitude=request.form.get("venue_latitude", type=float),
        venue_longitude=request.form.get("venue_longitude", type=float),
        venue_radius=request.form.get("venue_radius", 100.0, type=float),
    )
    flash("Event updated successfully.", "success")
    return redirect(url_for("admin.events_list"))


@admin_bp.route("/events/<int:event_id>/delete", methods=["POST"])
@login_required
def events_delete(event_id):
    csrf_protect()
    db = get_db()
    delete_event(db, event_id)
    flash("Event deleted.", "info")
    return redirect(url_for("admin.events_list"))


@admin_bp.route("/events/<int:event_id>/activate", methods=["POST"])
@login_required
def events_activate(event_id):
    csrf_protect()
    db = get_db()
    set_event_active(db, event_id, True)
    flash("Event activated.", "success")
    return redirect(url_for("admin.events_list"))


@admin_bp.route("/events/<int:event_id>/deactivate", methods=["POST"])
@login_required
def events_deactivate(event_id):
    csrf_protect()
    db = get_db()
    set_event_active(db, event_id, False)
    flash("Event deactivated.", "info")
    return redirect(url_for("admin.events_list"))


@admin_bp.route("/events/<int:event_id>/generate-qr", methods=["POST"])
@login_required
def events_generate_qr(event_id):
    csrf_protect()
    db = get_db()
    event = get_event(db, event_id)
    if event is None:
        flash("Event not found.", "danger")
        return redirect(url_for("admin.events_list"))

    validity = request.form.get("validity_minutes", type=int) or current_app.config["QR_DEFAULT_VALIDITY_MINUTES"]
    result = generate_event_qr(
        db, event_id,
        base_url=request.url_root,
        qr_folder=current_app.config["QR_FOLDER"],
        validity_minutes=validity,
    )
    flash(f"QR generated. Valid until {result['expires_at'].strftime('%Y-%m-%d %H:%M UTC')}.", "success")
    return redirect(url_for("admin.events_list"))


# =========================================================================
# Attendance browsing
# =========================================================================

@admin_bp.route("/attendance")
@login_required
def attendance_list():
    db = get_db()

    search = request.args.get("search", "").strip()
    event_id = request.args.get("event_id", type=int)
    branch = request.args.get("branch", "").strip()
    only_flagged = request.args.get("only_flagged") == "1"
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 25

    where_clauses = []
    params = []

    if search:
        where_clauses.append(
            "(student_name LIKE ? OR crn LIKE ? OR urn LIKE ? OR phone LIKE ?)"
        )
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if event_id:
        where_clauses.append("event_id = ?")
        params.append(event_id)

    if branch:
        where_clauses.append("branch = ?")
        params.append(branch)

    if only_flagged:
        where_clauses.append("(is_duplicate = 1 OR is_proxy_suspected = 1)")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    total = db.execute(f"SELECT COUNT(*) AS c FROM attendance {where_sql}", params).fetchone()["c"]
    rows = db.execute(
        f"""SELECT * FROM attendance {where_sql}
            ORDER BY created_at DESC LIMIT ? OFFSET ?""",
        params + [per_page, (page - 1) * per_page],
    ).fetchall()

    events = get_all_events(db)
    branches = [r["branch"] for r in db.execute(
        "SELECT DISTINCT branch FROM attendance WHERE branch IS NOT NULL AND branch != '' ORDER BY branch"
    ).fetchall()]

    total_pages = max((total + per_page - 1) // per_page, 1)

    return render_template(
        "admin/attendance.html",
        rows=rows, events=events, branches=branches,
        search=search, event_id=event_id, branch=branch, only_flagged=only_flagged,
        page=page, total_pages=total_pages, total=total,
    )


# =========================================================================
# Live QR Screen (Phase 2/3 countdown + refresh)
# =========================================================================

@admin_bp.route("/events/<int:event_id>/live-qr")
@login_required
def event_live_qr(event_id):
    db = get_db()
    event = get_event(db, event_id)
    if not event:
        flash("Event not found.", "danger")
        return redirect(url_for("admin.events_list"))
    return render_template("admin/live_qr.html", event=event)


@admin_bp.route("/events/<int:event_id>/live-qr/token")
@login_required
def event_live_qr_token(event_id):
    db = get_db()
    event = get_event(db, event_id)
    if not event:
        return {"success": False, "message": "Event not found"}, 404
    
    # Auto-regenerate QR if missing or expired
    from utils.qr_generator import is_qr_expired
    if not event["qr_token"] or is_qr_expired(event["qr_expires_at"]):
        generate_event_qr(
            db, event_id,
            base_url=request.url_root,
            qr_folder=current_app.config["QR_FOLDER"],
            validity_minutes=current_app.config["QR_DEFAULT_VALIDITY_MINUTES"]
        )
        event = get_event(db, event_id)
        
    from datetime import datetime
    try:
        expires_at = datetime.fromisoformat(event["qr_expires_at"])
        seconds_left = max(int((expires_at - datetime.utcnow()).total_seconds()), 0)
    except Exception:
        seconds_left = 0
        
    return {
        "success": True,
        "qr_token": event["qr_token"],
        "qr_image_url": url_for("static", filename=f"qrcodes/{event['qr_image_path']}"),
        "seconds_left": seconds_left,
        "expires_at": event["qr_expires_at"]
    }


# =========================================================================
# Location Analytics
# =========================================================================

@admin_bp.route("/location-analytics")
@login_required
def location_analytics():
    db = get_db()
    event_id = request.args.get("event_id", type=int)
    date_str = request.args.get("date", "").strip()
    
    where_clauses = ["latitude IS NOT NULL", "longitude IS NOT NULL"]
    params = []
    
      
    if event_id:
        where_clauses.append("event_id = ?")
        params.append(event_id)
    if date_str:
        where_clauses.append("date(created_at) = date(?)")
        params.append(date_str)
        
    where_sql = f"WHERE {' AND '.join(where_clauses)}"
    
    query = f"""SELECT id, student_name, crn, urn, event_name, latitude, longitude, 
                       location_address, location_status, risk_score, created_at 
                FROM attendance {where_sql} ORDER BY created_at DESC"""
    rows = db.execute(query, params).fetchall()
    events = get_all_events(db)
    
    records = []
    for r in rows:
        records.append({
            "id": r["id"],
            "student_name": r["student_name"],
            "crn_urn": f"{r['crn'] or '-'}/{r['urn'] or '-'}",
            "event_name": r["event_name"],
            "lat": r["latitude"],
            "lng": r["longitude"],
            "address": r["location_address"] or "No geocoded address captured",
            "status": r["location_status"],
            "risk": r["risk_score"]
        })
        
    return render_template(
        "admin/location_analytics.html",
        records=records,
        events=events,
        event_id=event_id,
        date_str=date_str
    )


# =========================================================================
# OCR Document Processing
# =========================================================================

@admin_bp.route("/ocr")
@login_required
def ocr_dashboard():
    db = get_db()
    uploads = db.execute("SELECT * FROM ocr_uploads ORDER BY created_at DESC").fetchall()
    events = get_active_events(db)
    return render_template("admin/ocr_dashboard.html", uploads=uploads, events=events)


@admin_bp.route("/ocr/upload", methods=["POST"])
@login_required
def ocr_upload():
    csrf_protect()
    db = get_db()
    
    event_id = request.form.get("event_id", type=int)
    if not event_id:
        flash("Please select an event for the uploaded sheet.", "danger")
        return redirect(url_for("admin.ocr_dashboard"))
        
    if "attendance_file" not in request.files:
        flash("No file part found in request.", "danger")
        return redirect(url_for("admin.ocr_dashboard"))
        
    file = request.files["attendance_file"]
    if file.filename == "":
        flash("No file was selected for upload.", "danger")
        return redirect(url_for("admin.ocr_dashboard"))
        
    ext = file.filename.split(".")[-1].lower()
    if ext not in current_app.config["ALLOWED_OCR_EXTENSIONS"]:
        flash(f"File type .{ext} is not supported.", "danger")
        return redirect(url_for("admin.ocr_dashboard"))
        
    # Generate storage filename
    filename = f"ocr_upload_{secrets.token_hex(8)}.{ext}"
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)
    file_path = os.path.join(upload_folder, filename)
    file.save(file_path)
    
    # Save upload job in processing state
    from flask import session
    cur = db.execute(
        """INSERT INTO ocr_uploads (original_filename, stored_filename, file_type, event_id, uploaded_by, status)
           VALUES (?, ?, ?, ?, ?, 'processing')""",
        (file.filename, filename, ext, event_id, session["admin_id"])
    )
    db.commit()
    upload_id = cur.lastrowid
    
    # Process job synchronously
    from utils.ocr_helper import process_ocr_upload
    try:
        process_ocr_upload(db, upload_id, file_path, ext, event_id)
        flash("Attendance document uploaded and parsed.", "success")
    except Exception as e:
        flash(f"OCR Parsing failed: {str(e)}", "danger")
        
    return redirect(url_for("admin.ocr_details", upload_id=upload_id))


@admin_bp.route("/ocr/<int:upload_id>")
@login_required
def ocr_details(upload_id):
    db = get_db()
    upload = db.execute("SELECT * FROM ocr_uploads WHERE id = ?", (upload_id,)).fetchone()
    if not upload:
        flash("OCR Job details not found.", "danger")
        return redirect(url_for("admin.ocr_dashboard"))
        
    extracted_rows = db.execute(
        """SELECT r.*, s.student_name AS roster_name, s.branch AS roster_branch, s.section AS roster_section
           FROM ocr_extracted_rows r
           LEFT JOIN students s ON r.matched_student_id = s.id
           WHERE r.ocr_upload_id = ?""",
        (upload_id,)
    ).fetchall()
    
    event = get_event(db, upload["event_id"])
    return render_template(
        "admin/ocr_details.html",
        upload=upload,
        extracted_rows=extracted_rows,
        event=event
    )


@admin_bp.route("/ocr/<int:upload_id>/import", methods=["POST"])
@login_required
def ocr_import(upload_id):
    csrf_protect()
    db = get_db()
    upload = db.execute("SELECT * FROM ocr_uploads WHERE id = ?", (upload_id,)).fetchone()
    if not upload:
        flash("Roster import job not found.", "danger")
        return redirect(url_for("admin.ocr_dashboard"))
        
    # Query non-duplicate rows that matched students
    extracted_rows = db.execute(
        """SELECT r.*, s.student_name, s.branch, s.section, s.is_nss_volunteer
           FROM ocr_extracted_rows r
           LEFT JOIN students s ON r.matched_student_id = s.id
           WHERE r.ocr_upload_id = ? AND r.is_duplicate_in_db = 0""",
        (upload_id,)
    ).fetchall()
    
    event = get_event(db, upload["event_id"])
    imported_count = 0
    from datetime import datetime
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    
    for r in extracted_rows:
        # Check database double-submission
        dup = db.execute(
            """SELECT COUNT(*) AS c FROM attendance 
               WHERE event_id = ? AND (
                   (crn = ? AND crn IS NOT NULL) OR 
                   (urn = ? AND urn IS NOT NULL)
               )""",
            (upload["event_id"], r["extracted_crn"] or None, r["extracted_urn"] or None)
        ).fetchone()
        if dup and dup["c"] > 0:
            continue
            
        db.execute(
            """INSERT INTO attendance (
                    student_name, branch, section, crn, urn, phone, is_nss_volunteer,
                    attendance_mode, event_id, event_name,
                    latitude, longitude, location_address, google_maps_link, location_status,
                    gps_accuracy_m, ip_address, browser, device,
                    is_duplicate, is_proxy_suspected, risk_score, ocr_upload_id, location_timestamp
               ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ocr', ?, ?, NULL, NULL, 'Imported from Scanned sheet (OCR Center)', NULL, 'captured',
                         NULL, 'uploaded-sheet', 'OCR-Engine', 'Admin-Upload', 0, 0, 0, ?, ?)""",
            (
                r["extracted_name"] or r["student_name"] or "Unknown Student",
                r["branch"] or "-",
                r["section"] or "-",
                r["extracted_crn"] or None,
                r["extracted_urn"] or None,
                r["extracted_phone"] or "-",
                r["is_nss_volunteer"] or 0,
                upload["event_id"],
                event["event_name"],
                upload_id,
                now_str
            )
        )
        db.execute("UPDATE ocr_extracted_rows SET accepted = 1 WHERE id = ?", (r["id"],))
        imported_count += 1
        
    from flask import session
    db.execute(
        "INSERT INTO audit_log (admin_id, action, details, ip_address) VALUES (?, 'ocr_import', ?, ?)",
        (session["admin_id"], f"Batch imported {imported_count} check-ins from OCR Job #{upload_id}", get_client_ip())
    )
    db.commit()
    flash(f"Imported {imported_count} student attendance records.", "success")
    return redirect(url_for("admin.ocr_details", upload_id=upload_id))


@admin_bp.route("/ocr/<int:upload_id>/excel")
@login_required
def ocr_export_excel(upload_id):
    db = get_db()
    upload = db.execute("SELECT * FROM ocr_uploads WHERE id = ?", (upload_id,)).fetchone()
    if not upload:
        return "OCR Job details not found", 404
        
    extracted_rows = db.execute(
        "SELECT * FROM ocr_extracted_rows WHERE ocr_upload_id = ?",
        (upload_id,)
    ).fetchall()
    
    filename = f"ocr_report_{upload_id}.xlsx"
    filepath = os.path.join(current_app.config["EXCEL_EXPORT_FOLDER"], filename)
    
    from utils.excel_exporter import export_ocr_report_excel
    export_ocr_report_excel(upload, extracted_rows, filepath)
    return send_file(filepath, as_attachment=True, download_name=filename)


# =========================================================================
# Student Master Roster
# =========================================================================

@admin_bp.route("/students")
@login_required
def students_list():
    db = get_db()
    search = request.args.get("search", "").strip()
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 50
    
    where_sql = ""
    params = []
    if search:
        where_sql = "WHERE student_name LIKE ? OR crn LIKE ? OR urn LIKE ? OR phone LIKE ? OR branch LIKE ?"
        like = f"%{search}%"
        params.extend([like, like, like, like, like])
        
    total = db.execute(f"SELECT COUNT(*) AS c FROM students {where_sql}", params).fetchone()["c"]
    rows = db.execute(
        f"SELECT * FROM students {where_sql} ORDER BY student_name LIMIT ? OFFSET ?",
        params + [per_page, (page - 1) * per_page]
    ).fetchall()
    
    total_pages = max((total + per_page - 1) // per_page, 1)
    return render_template(
        "admin/students.html",
        rows=rows, search=search, page=page, total_pages=total_pages, total=total
    )


@admin_bp.route("/students/import", methods=["POST"])
@login_required
def students_import():
    csrf_protect()
    db = get_db()
    
    if "roster_file" not in request.files:
        flash("Roster file upload field missing.", "danger")
        return redirect(url_for("admin.students_list"))
        
    file = request.files["roster_file"]
    if file.filename == "":
        flash("No file was chosen for upload.", "danger")
        return redirect(url_for("admin.students_list"))
        
    ext = file.filename.split(".")[-1].lower()
    if ext not in current_app.config["ALLOWED_IMPORT_EXTENSIONS"]:
        flash(f"Unsupported spreadsheet format: .{ext}", "danger")
        return redirect(url_for("admin.students_list"))
        
    filename = f"roster_import_{secrets.token_hex(8)}.{ext}"
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)
    file_path = os.path.join(upload_folder, filename)
    file.save(file_path)
    
    from utils.ocr_helper import parse_tabular_file
    try:
        rows = parse_tabular_file(file_path, ext)
        inserted_count = 0
        for r in rows:
            existing = None
            if r["urn"]:
                existing = db.execute("SELECT * FROM students WHERE urn = ?", (r["urn"],)).fetchone()
            elif r["crn"]:
                existing = db.execute("SELECT * FROM students WHERE crn = ?", (r["crn"],)).fetchone()
                
            if existing:
                continue
                
            db.execute(
                """INSERT INTO students (student_name, branch, section, crn, urn, phone, is_nss_volunteer)
                   VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (r["student_name"] or "Unknown Student", r["branch"] or "-", r["section"] or "-", r["crn"] or None, r["urn"] or None, r["phone"] or "-")
            )
            inserted_count += 1
            
        from flask import session
        db.execute(
            "INSERT INTO audit_log (admin_id, action, details, ip_address) VALUES (?, 'roster_import', ?, ?)",
            (session["admin_id"], f"Uploaded roster: added {inserted_count} student volunteers", get_client_ip())
        )
        db.commit()
        flash(f"Roster uploaded: imported {inserted_count} new student profiles.", "success")
    except Exception as e:
        flash(f"Error parsing roster file: {str(e)}", "danger")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
            
    return redirect(url_for("admin.students_list"))


# =========================================================================
# Reports & PDF/Excel Export
# =========================================================================

@admin_bp.route("/reports")
@login_required
def reports_view():
    db = get_db()
    events = get_all_events(db)
    branches = [r["branch"] for r in db.execute(
        "SELECT DISTINCT branch FROM attendance WHERE branch IS NOT NULL AND branch != '' ORDER BY branch"
    ).fetchall()]
    return render_template("admin/reports.html", events=events, branches=branches)


@admin_bp.route("/reports/download")
@login_required
def reports_download():
    db = get_db()
    fmt = request.args.get("format", "excel").lower()
    event_id = request.args.get("event_id", type=int)
    branch = request.args.get("branch", "").strip()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    only_volunteers = request.args.get("only_volunteers") == "1"
    only_flagged = request.args.get("only_flagged") == "1"
    
    where_clauses = []
    params = []
    
    if event_id:
        where_clauses.append("event_id = ?")
        params.append(event_id)
    if branch:
        where_clauses.append("branch = ?")
        params.append(branch)
    if start_date:
        where_clauses.append("date(created_at) >= date(?)")
        params.append(start_date)
    if end_date:
        where_clauses.append("date(created_at) <= date(?)")
        params.append(end_date)
    if only_volunteers:
        where_clauses.append("is_nss_volunteer = 1")
    if only_flagged:
        where_clauses.append("(is_duplicate = 1 OR is_proxy_suspected = 1)")
        
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    rows = db.execute(
        f"SELECT * FROM attendance {where_sql} ORDER BY created_at DESC",
        params
    ).fetchall()
    
    if not rows:
        flash("No attendance logs matched the filters selected.", "warning")
        return redirect(url_for("admin.reports_view"))
        
    event = get_event(db, event_id) if event_id else None
    title = event["event_name"] if event else "All Events"
    
    os.makedirs(current_app.config["EXCEL_EXPORT_FOLDER"], exist_ok=True)
    
    if fmt == "excel":
        filename = f"attendance_report_{secrets.token_hex(4)}.xlsx"
        filepath = os.path.join(current_app.config["EXCEL_EXPORT_FOLDER"], filename)
        from utils.excel_exporter import export_attendance_excel
        export_attendance_excel(rows, filepath)
        return send_file(filepath, as_attachment=True, download_name=f"Attendance_Report_{title.replace(' ', '_')}.xlsx")
        
    elif fmt == "pdf":
        filename = f"attendance_report_{secrets.token_hex(4)}.pdf"
        filepath = os.path.join(current_app.config["EXCEL_EXPORT_FOLDER"], filename)
        from utils.pdf_generator import export_attendance_pdf
        export_attendance_pdf(rows, title, filepath)
        return send_file(filepath, as_attachment=True, download_name=f"Attendance_Report_{title.replace(' ', '_')}.pdf")
        
    elif fmt == "csv":
        import csv
        filename = f"attendance_report_{secrets.token_hex(4)}.csv"
        filepath = os.path.join(current_app.config["EXCEL_EXPORT_FOLDER"], filename)
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Student Name", "Branch", "Section", "CRN", "URN", "Phone", 
                "NSS Volunteer", "Mode", "Event Name", "Timestamp", 
                "Latitude", "Longitude", "Location Address", "Status", "Risk Score"
            ])
            for r in rows:
                writer.writerow([
                    r["student_name"], r["branch"] or "-", r["section"] or "-",
                    r["crn"] or "-", r["urn"] or "-", r["phone"],
                    "Yes" if r["is_nss_volunteer"] == 1 else "No",
                    r["attendance_mode"], r["event_name"], r["created_at"],
                    r["latitude"], r["longitude"], r["location_address"] or "-",
                    r["location_status"], r["risk_score"]
                ])
        return send_file(filepath, as_attachment=True, download_name=f"Attendance_Report_{title.replace(' ', '_')}.csv")
        
    flash("Requested download format invalid.", "danger")
    return redirect(url_for("admin.reports_view"))

