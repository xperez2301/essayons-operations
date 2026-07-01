from flask import Blueprint, jsonify, render_template, session, redirect, url_for, request, current_app

database_center_bp = Blueprint("database_center", __name__)


def database_admin_required():
    if not session.get("logged_in"):
        return redirect(url_for("login", next=request.path))
    if session.get("role") != "Admin":
        return render_template("access_denied.html"), 403
    return None


@database_center_bp.route("/database-center-v2/health")
def database_center_v2_health():
    return jsonify({
        "status": "ok",
        "module": "Database Center 2.0",
        "message": "Database Center Blueprint is active."
    })


@database_center_bp.route("/database-center")
def database_center():
    blocked = database_admin_required()
    if blocked:
        return blocked
    return render_template("database_center.html")

@database_center_bp.route("/database-health")
def database_health():
    blocked = database_admin_required()
    if blocked:
        return blocked

    database_health_report = current_app.config["DATABASE_HEALTH_REPORT"]
    stores_file = current_app.config["STORES_FILE"]
    bol_dir = current_app.config["BOL_DIR"]
    upload_dir = current_app.config["UPLOAD_DIR"]

    report = database_health_report(stores_file, bol_dir, upload_dir)
    return render_template("database_health.html", report=report)