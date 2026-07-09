"""Reporting workspace blueprint.

FT6 blueprint split: relocates Flask routing/glue code out of app.py.
Business logic stays in eoms_modules.reporting_service, unchanged. The
automation-center health lookup keeps its original best-effort try/except
shape (falling back to an OFFLINE status) exactly as it did in app.py.
"""

from flask import Blueprint, render_template

from app import (
    STORES_FILE,
    ROUTES_FILE,
    ROADMAP_FILE,
    read_json,
    filter_stores_for_user,
    filter_routes_for_user,
    build_roadmap_workspace,
)
from eoms_modules.reporting_service import build_reporting_workspace

reporting_bp = Blueprint("reporting", __name__)


@reporting_bp.route("/reporting")
def reporting_workspace():
    stores = filter_stores_for_user(read_json(STORES_FILE))
    routes = filter_routes_for_user(read_json(ROUTES_FILE))
    roadmap = build_roadmap_workspace(ROADMAP_FILE)

    try:
        from eoms_modules.automation_center_manager import automation_center
        automation_status = automation_center.center_health()
    except Exception as exc:
        automation_status = {
            "status": "OFFLINE",
            "worker_health": "OFFLINE",
            "error": str(exc),
        }

    workspace = build_reporting_workspace(
        stores=stores,
        routes=routes,
        roadmap_workspace=roadmap,
        automation_status=automation_status,
    )
    return render_template("reporting.html", workspace=workspace)
