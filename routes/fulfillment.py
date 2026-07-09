"""Fulfillment workspace blueprint.

FT6 blueprint split: relocates Flask routing/glue code out of app.py.
Business logic stays in eoms_modules.fulfillment_service, unchanged.
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
from eoms_modules.fulfillment_service import build_fulfillment_workspace, reserve_inventory, ship_order

fulfillment_bp = Blueprint("fulfillment", __name__)


@fulfillment_bp.route("/fulfillment")
def fulfillment_workspace():
    stores = filter_stores_for_user(read_json(STORES_FILE))
    workspace = build_fulfillment_workspace(stores, request.args.get("order"))
    return render_template("fulfillment.html", workspace=workspace)


@fulfillment_bp.route("/api/fulfillment/reserve", methods=["POST"])
@synchronized_data_write(STORES_FILE)
def api_fulfillment_reserve():
    data = request.get_json(force=True) or {}
    stores = read_json(STORES_FILE)

    try:
        order = reserve_inventory(
            stores,
            data,
            reserved_by=session.get("username", "system"),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    write_json(STORES_FILE, stores)
    workspace = build_fulfillment_workspace(stores, order.get("order_number"))
    audit("Reserve Fulfillment Inventory", {"order_number": order.get("order_number"), "customer": order.get("customer")})

    return jsonify({
        "ok": True,
        "order": order,
        "summary": workspace.get("summary", {}),
    })


@fulfillment_bp.route("/api/fulfillment/ship", methods=["POST"])
@synchronized_data_write(STORES_FILE)
def api_fulfillment_ship():
    data = request.get_json(force=True) or {}
    stores = read_json(STORES_FILE)

    try:
        order = ship_order(
            stores,
            data.get("order_number"),
            shipped_by=session.get("username", "system"),
            shipment_notes=data.get("shipment_notes"),
        )
        already_shipped = bool(order.pop("already_shipped", False))
    except LookupError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    write_json(STORES_FILE, stores)
    workspace = build_fulfillment_workspace(stores, order.get("order_number"))
    audit("Ship Fulfillment Order", {"order_number": order.get("order_number"), "already_shipped": already_shipped})

    return jsonify({
        "ok": True,
        "already_shipped": already_shipped,
        "order": order,
        "summary": workspace.get("summary", {}),
    })
