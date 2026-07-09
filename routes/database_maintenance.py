"""Database Maintenance API blueprint.

FT6 blueprint split: relocates Flask routing/glue code out of app.py.
Business logic stays in database_tools.py, unchanged. This is a separate
blueprint from routes/database_center.py (which registers earlier, at the
top of app.py, before STORES_FILE/admin_required/etc. exist) so that file's
existing early-import ordering doesn't need to change.
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from app import (
    STORES_FILE,
    BASE_DIR,
    BOL_DIR,
    UPLOAD_DIR,
    admin_required,
    audit,
    clean,
)
from database_tools import (
    backup_stores_json,
    database_health as database_health_report,
    repair_duplicate_bols,
)

database_maintenance_bp = Blueprint("database_maintenance", __name__)


@database_maintenance_bp.route("/api/database/backup", methods=["POST"])
@admin_required
def api_database_backup():
    backup_path = backup_stores_json(STORES_FILE, BASE_DIR / "backups", reason="manual_backup")
    result = {"ok": True, "backup_path": str(backup_path), "message": "Database backup created."}
    audit("Database Backup", result)
    return jsonify(result)


@database_maintenance_bp.route("/api/database/repair-duplicates", methods=["POST"])
@admin_required
def api_database_repair_duplicates():
    result = repair_duplicate_bols(STORES_FILE, BASE_DIR / "backups", BOL_DIR, UPLOAD_DIR)
    audit("Repair Duplicate BOLs", result)
    return jsonify(result)


@database_maintenance_bp.route("/api/database/duplicates")
@admin_required
def api_database_duplicates():
    report = database_health_report(STORES_FILE, BOL_DIR, UPLOAD_DIR)
    return jsonify({
        "ok": True,
        "duplicate_count": report.get("duplicate_bol_count", 0),
        "duplicates": report.get("duplicates", []),
    })


@database_maintenance_bp.route("/api/database/missing-pdfs")
@admin_required
def api_database_missing_pdfs():
    report = database_health_report(STORES_FILE, BOL_DIR, UPLOAD_DIR)
    return jsonify({
        "ok": True,
        "missing_pdf_count": report.get("missing_pdf_count", 0),
        "missing_pdfs": report.get("missing_pdfs", []),
    })


@database_maintenance_bp.route("/api/database/orphan-pdfs")
@admin_required
def api_database_orphan_pdfs():
    report = database_health_report(STORES_FILE, BOL_DIR, UPLOAD_DIR)
    return jsonify({
        "ok": True,
        "orphan_pdf_count": report.get("orphan_pdf_count", 0),
        "orphan_pdfs": report.get("orphan_pdfs", []),
    })


@database_maintenance_bp.route("/api/database/backups")
@admin_required
def api_database_backups():
    backups_dir = BASE_DIR / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for p in sorted(backups_dir.glob("stores_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        files.append({
            "name": p.name,
            "path": str(p),
            "size_bytes": p.stat().st_size,
            "modified_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
        })

    return jsonify({"ok": True, "backups": files, "count": len(files)})


@database_maintenance_bp.route("/api/database/restore-backup", methods=["POST"])
@admin_required
def api_database_restore_backup():
    import shutil

    data = request.get_json(force=True)
    backup_name = clean(data.get("backup_name"))

    backups_dir = BASE_DIR / "backups"
    backup_path = backups_dir / backup_name

    if not backup_name or not backup_path.exists() or backup_path.parent.resolve() != backups_dir.resolve():
        return jsonify({"ok": False, "message": "Invalid backup selected."}), 400

    safety_backup = backup_stores_json(STORES_FILE, backups_dir, reason="before_restore")
    shutil.copy2(backup_path, STORES_FILE)

    result = {
        "ok": True,
        "message": "Backup restored successfully.",
        "restored_from": str(backup_path),
        "safety_backup": str(safety_backup),
    }
    audit("Restore Database Backup", result)
    return jsonify(result)
