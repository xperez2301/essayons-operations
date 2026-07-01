from flask import Blueprint, jsonify

database_center_bp = Blueprint("database_center", __name__)


@database_center_bp.route("/database-center-v2/health")
def database_center_v2_health():
    return jsonify({
        "status": "ok",
        "module": "Database Center 2.0",
        "message": "Database Center Blueprint is active."
    })