"""
app.py
Application entrypoint / factory for the NSS Attendance Management System.

Run locally with:   python app.py
Deploy on PythonAnywhere by pointing the WSGI config at `app` (see README.md).
"""

from flask import Flask, render_template, redirect, url_for, current_app

from config import get_config
from database import init_db, register_db


def create_app():
    app = Flask(__name__)
    app.config.from_object(get_config())

    # Ensure folders exist + schema is applied + default admin seeded.
    init_db(app)
    register_db(app)

    # ---- Blueprints -----------------------------------------------
    from routes.auth import auth_bp
    from routes.student import student_bp
    from routes.admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(admin_bp)

    # ---- Root route -------------------------------------------------
    @app.route("/")
    def index():
        return redirect(url_for("student.attend_manual"))

    # ---- Error handlers ----------------------------------------------
    @app.errorhandler(400)
    def bad_request(e):
        return render_template("errors/error.html", code=400,
                                message=getattr(e, "description", "Bad request.")), 400

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/error.html", code=403,
                                message="You don't have permission to access this."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/error.html", code=404,
                                message="The page you're looking for doesn't exist."), 404

    @app.errorhandler(410)
    def gone(e):
        return render_template("errors/error.html", code=410,
                                message="This resource is no longer available."), 410

    @app.errorhandler(500)
    def server_error(e):
        current_app.logger.exception("Unhandled server error")
        return render_template("errors/error.html", code=500,
                                message="Something went wrong on our end."), 500

    # ---- Security headers ---------------------------------------------
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=app.config.get("DEBUG", False))
