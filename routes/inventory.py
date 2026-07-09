"""Inventory workspace blueprint.

FT6 blueprint split: relocates Flask routing/glue code out of app.py.
Business logic stays in eoms_modules.inventory_service, unchanged.
"""

from flask import Blueprint, jsonify, render_template, request, session

from app import (
    STORES_FILE,
    read_json,
    write_json,
    synchronized_data_write,
    filter_stores_for_user,
    audit,
)
from eoms_modules.inventory_service import build_inventory_workspace, adjust_inventory

inventory_bp = Blueprint("inventory", __name__)


@inventory_bp.route("/inventory")
def inventory_workspace():
    stores = filter_stores_for_user(read_json(STORES_FILE))
    workspace = build_inventory_workspace(stores, request.args.get("component"))
    return render_template("inventory.html", workspace=workspace)


@inventory_bp.route("/api/inventory/adjust", methods=["POST"])
@synchronized_data_write(STORES_FILE)
def api_inventory_adjust():
    data = request.get_json(force=True) or {}
    stores = read_json(STORES_FILE)

    try:
        adjustment = adjust_inventory(
            stores,
            data.get("component"),
            data.get("amount"),
            data.get("reason"),
            adjusted_by=session.get("username", "system"),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    write_json(STORES_FILE, stores)
    workspace = build_inventory_workspace(stores, adjustment.get("component"))
    audit("Adjust Inventory", adjustment)

    return jsonify({
        "ok": True,
        "adjustment": adjustment,
        "summary": workspace.get("summary", {}),
    })
