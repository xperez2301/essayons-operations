"""Database Maintenance API blueprint.

FT6 blueprint split: relocates Flask routing/glue code out of app.py.
Business logic stays in database_tools.py, unchanged. This is a separate
blueprint from routes/database_center.py (which registers earlier, at the
top of app.py, before STORES_FILE/admin_required/etc. exist) so that file's
existing early-import ordering doesn't need to change.
"""

import json
from datetime import datetime

from flask import Blueprint, Response, jsonify, render_template, request, session

from app import (
    AUDIT_FILE,
    BASE_DIR,
    BOL_DIR,
    RMS_QUEUE_FILE,
    ROUTES_FILE,
    STORES_FILE,
    SYNC_HISTORY_FILE,
    UPLOAD_DIR,
    admin_required,
    audit,
    clean,
    read_json,
    synchronized_data_write,
    write_json,
)
from database_tools import (
    backup_stores_json,
    database_health as database_health_report,
    repair_duplicate_bols,
)
from eoms_modules.duplicate_bol_cleanup_service import (
    backup_runtime_files,
    cleanup_safe_duplicates,
    find_latest_cleanup_manifest,
    restore_backup_manifest,
    scan_duplicate_bols,
)

database_maintenance_bp = Blueprint("database_maintenance", __name__)


def _duplicate_bol_backup_root():
    root = BASE_DIR / "backups"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _duplicate_bol_runtime_files():
    return {
        "stores": STORES_FILE,
        "routes": ROUTES_FILE,
        "rms_queue": RMS_QUEUE_FILE,
        "sync_history": SYNC_HISTORY_FILE,
        "audit": AUDIT_FILE,
    }


def _duplicate_bol_snapshot():
    return {
        "stores": read_json(STORES_FILE),
        "routes": read_json(ROUTES_FILE),
        "rms_queue": read_json(RMS_QUEUE_FILE),
        "sync_history": read_json(SYNC_HISTORY_FILE),
        "audit_entries": read_json(AUDIT_FILE),
        "last_cleanup": find_latest_cleanup_manifest(_duplicate_bol_backup_root()),
    }


@database_maintenance_bp.route("/admin/duplicate-bols")
@admin_required
def duplicate_bol_cleanup_page():
    return render_template("duplicate_bol_cleanup.html")


@database_maintenance_bp.route("/api/admin/duplicate-bols/scan", methods=["POST"])
@admin_required
def api_duplicate_bol_scan():
    snapshot = _duplicate_bol_snapshot()
    report = scan_duplicate_bols(**snapshot)
    return jsonify(report)


@database_maintenance_bp.route("/api/admin/duplicate-bols/cleanup", methods=["POST"])
@admin_required
@synchronized_data_write(STORES_FILE, ROUTES_FILE, RMS_QUEUE_FILE, SYNC_HISTORY_FILE, AUDIT_FILE)
def api_duplicate_bol_cleanup():
    snapshot = _duplicate_bol_snapshot()
    kept, removed, scan_before = cleanup_safe_duplicates(
        snapshot["stores"],
        snapshot["routes"],
        snapshot["audit_entries"],
        snapshot["rms_queue"],
        snapshot["sync_history"],
    )
    safe_count = len(removed)
    if safe_count == 0:
        return jsonify({
            "ok": True,
            "message": "No safe duplicate BOL records were eligible for cleanup.",
            "removed_count": 0,
            "scan": scan_before,
        })

    try:
        backup_manifest = backup_runtime_files(_duplicate_bol_runtime_files(), _duplicate_bol_backup_root())
    except Exception as exc:
        return jsonify({
            "ok": False,
            "message": f"Cleanup stopped before any data was changed because backup creation failed: {exc}",
        }), 500
    try:
        write_json(STORES_FILE, kept)
        verification = scan_duplicate_bols(
            read_json(STORES_FILE),
            read_json(ROUTES_FILE),
            read_json(AUDIT_FILE),
            read_json(RMS_QUEUE_FILE),
            read_json(SYNC_HISTORY_FILE),
            last_cleanup=backup_manifest,
        )
    except Exception:
        restore_backup_manifest(backup_manifest, _duplicate_bol_runtime_files())
        raise

    result = {
        "ok": True,
        "message": f"Removed {safe_count} safe duplicate BOL record{'s' if safe_count != 1 else ''}.",
        "removed_count": safe_count,
        "removed_records": [
            {
                "id": clean(item.get("id")),
                "bol": clean(item.get("bol")),
            }
            for item in removed
        ],
        "backup": {
            "name": backup_manifest.get("name"),
            "timestamp": backup_manifest.get("timestamp"),
        },
        "verification": verification,
    }
    audit("Duplicate BOL Cleanup", {
        "user": session.get("username", "unknown"),
        "removed_count": safe_count,
        "backup": backup_manifest.get("name"),
    })
    return jsonify(result)


@database_maintenance_bp.route("/api/admin/duplicate-bols/rollback", methods=["POST"])
@admin_required
@synchronized_data_write(STORES_FILE, ROUTES_FILE, RMS_QUEUE_FILE, SYNC_HISTORY_FILE, AUDIT_FILE)
def api_duplicate_bol_rollback():
    data = request.get_json(silent=True) or {}
    if clean(data.get("confirmation")) != "ROLLBACK":
        return jsonify({"ok": False, "message": "Type ROLLBACK to restore the latest duplicate cleanup backup."}), 400

    backup_root = _duplicate_bol_backup_root()
    manifest = find_latest_cleanup_manifest(backup_root)
    if not manifest:
        return jsonify({"ok": False, "message": "No duplicate BOL cleanup backup is available to roll back."}), 404

    safety_manifest = backup_runtime_files(
        _duplicate_bol_runtime_files(),
        backup_root,
        label="duplicate_bol_pre_rollback",
    )
    restored = restore_backup_manifest(manifest, _duplicate_bol_runtime_files())
    verification = scan_duplicate_bols(
        read_json(STORES_FILE),
        read_json(ROUTES_FILE),
        read_json(AUDIT_FILE),
        read_json(RMS_QUEUE_FILE),
        read_json(SYNC_HISTORY_FILE),
        last_cleanup=manifest,
    )
    result = {
        "ok": True,
        "message": "Latest duplicate BOL cleanup backup restored.",
        "restored_from": manifest.get("name"),
        "safety_backup": safety_manifest.get("name"),
        "restored_files": restored,
        "verification": verification,
    }
    audit("Duplicate BOL Cleanup Rollback", {
        "user": session.get("username", "unknown"),
        "restored_from": manifest.get("name"),
        "safety_backup": safety_manifest.get("name"),
    })
    return jsonify(result)


@database_maintenance_bp.route("/api/admin/duplicate-bols/report")
@admin_required
def api_duplicate_bol_report():
    snapshot = _duplicate_bol_snapshot()
    report = scan_duplicate_bols(**snapshot)
    payload = json.dumps(report, indent=2)
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=duplicate-bol-audit-report.json"},
    )


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
