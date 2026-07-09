"""Recovery Center workspace blueprint.

FT6 blueprint split: relocates Flask routing/glue code out of app.py.
Business logic stays in eoms_modules.recovery_center_service, unchanged.
"""

from flask import Blueprint, render_template

from app import (
    STORES_FILE,
    ROUTES_FILE,
    SETTINGS_FILE,
    read_json,
    filter_stores_for_user,
    filter_routes_for_user,
    sms_status_payload,
)
from eoms_modules.recovery_center_service import summarize_recovery_workspace_from_records

recovery_center_bp = Blueprint("recovery_center", __name__)


@recovery_center_bp.route("/recovery")
def recovery_center():
    stores = filter_stores_for_user(read_json(STORES_FILE))
    routes = filter_routes_for_user(read_json(ROUTES_FILE))
    workspace = summarize_recovery_workspace_from_records(routes, stores)
    workspace["sms_status"] = sms_status_payload(read_json(SETTINGS_FILE))
    return render_template(
        "recovery_center.html",
        workspace=workspace,
    )
