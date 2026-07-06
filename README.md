# NSS Attendance Management System

An industry-grade, modular Flask application for tracking NSS (National
Service Scheme) attendance with mandatory GPS verification, QR-code
check-ins, event management, duplicate/proxy detection, and an admin
dashboard.

> **Build status:** Phase 1 of 4 complete — authentication, database,
> event management, QR attendance, manual attendance, location
> verification, duplicate/proxy detection, and the admin dashboard/
> attendance browser are implemented and tested end-to-end. OCR, Excel
> import/export, full analytics charts, and final UI polish ship in
> Phases 2–4 (see project chat for status).

---

## 1. Tech stack

- **Backend:** Python 3.13, Flask, SQLite
- **Location:** geopy (reverse geocoding), browser Geolocation API
- **QR codes:** `qrcode` + `Pillow`
- **Frontend:** Bootstrap 5, Bootstrap Icons, vanilla JS (Fetch/Geolocation APIs)

## 2. Project structure

```
nss_attendance/
├── app.py                  # Application factory + entrypoint
├── config.py                # All configuration (paths, security, thresholds)
├── database.py               # SQLite connection + schema bootstrap
├── schema.sql                 # Normalized DB schema
├── requirements.txt
├── routes/
│   ├── auth.py              # Admin login (username/password)
│   ├── student.py            # Public attendance form (manual + QR)
│   └── admin.py              # Dashboard, event CRUD, attendance browser
├── utils/
│   ├── location.py           # Reverse geocoding, distance, suspicious-location check
│   ├── qr_generator.py        # QR token/image generation + expiry
│   ├── duplicate_checker.py    # Duplicate attendance detection
│   ├── proxy_detector.py       # Risk scoring / proxy detection engine
│   ├── event_manager.py        # Event CRUD + QR lifecycle helpers
│   └── security.py            # CSRF protection, login_required, request metadata
├── templates/                 # Jinja2 templates (Bootstrap 5)
├── static/                    # CSS/JS/QR images
├── uploads/                    # Reserved for OCR/Excel uploads (Phase 3)
├── excel_reports/                # Reserved for Excel exports (Phase 2)
└── database/                    # SQLite file lives here (auto-created)
```

## 3. Setup (Windows / Linux / macOS)

```bash
cd nss_attendance
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

The app auto-creates the SQLite database, folders, and a default admin
account on first run:

- **Username:** `admin`
- **Password:** `ChangeMe@123`

**Change these immediately** by setting environment variables before the
first run (safest), or by updating the `admins` table afterward:

```bash
export NSS_ADMIN_USER=your_admin
export NSS_ADMIN_PASSWORD=your_strong_password
export NSS_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
```

Visit `http://localhost:5000/` for the student attendance form, and
`http://localhost:5000/auth/login` for the admin panel.

## 4. Deploying on PythonAnywhere

1. Upload/clone the project into your PythonAnywhere home directory.
2. Create a virtualenv and `pip install -r requirements.txt` inside it.
3. In the **Web** tab, create a new Flask app pointing at `app.py`, and
   set the virtualenv path.
4. In the WSGI configuration file PythonAnywhere generates, import the
   app object:
   ```python
   import sys
   path = '/home/yourusername/nss_attendance'
   if path not in sys.path:
       sys.path.append(path)
   from app import app as application
   ```
5. Set environment variables (`NSS_SECRET_KEY`, `NSS_ADMIN_USER`,
   `NSS_ADMIN_PASSWORD`) in the **Web > Environment variables** section.
6. Reload the web app. No code changes are required — all paths in
   `config.py` are computed relative to the project directory.

## 5. Security features implemented

- Password hashing (Werkzeug `generate_password_hash`/`check_password_hash`)
- Admin login (username + hashed password verification)
- CSRF protection on every state-changing form (session-bound tokens)
- Parameterized SQL everywhere (no string-built queries — SQL-injection safe)
- Server-side re-validation of all client-submitted data (location, event
  status, QR expiry) — never trusts the client
- Mandatory GPS capture enforced both client-side (disabled submit button)
  and server-side (rejects submissions with no coordinates)
- Duplicate attendance detection (same CRN/URN + event)
- Heuristic proxy/risk scoring (duplicate signals, suspicious distance from
  venue, missing location, rapid-fire submissions from one IP)
- Audit log of admin logins/logouts
- Security response headers (`X-Content-Type-Options`, `X-Frame-Options`, etc.)

## 6. What's tested

An automated end-to-end smoke test (login → event creation →
activation → QR generation → QR attendance → manual attendance →
duplicate rejection → missing-location rejection → expired/invalid QR
rejection → deactivated-event rejection → CSRF rejection → dashboard/
search rendering) passes against this exact codebase.

## 7. Roadmap (remaining phases)

- **Phase 2:** Analytics charts (branch/event/date trends), full Excel
  export with formatting, freeze panes, and filters.
- **Phase 3:** OCR pipeline for scanned/handwritten attendance sheets and
  bulk Excel import, with duplicate cross-checking and OCR reports.
- **Phase 4:** Glassmorphism dark/light theme polish, loading states,
  final hardening pass, and deployment documentation refresh.
