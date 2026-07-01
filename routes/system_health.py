from flask import Blueprint, current_app, jsonify


system_health_bp = Blueprint("system_health", __name__)


@system_health_bp.route("/api/system/health")
def api_system_health():
    service = current_app.config["SYSTEM_HEALTH_SERVICE"]
    return jsonify(service.status())