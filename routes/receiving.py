"""Receiving workspace blueprint.

FT6 step 3 of the app.py blueprint split (same pattern as
routes/driver_portal.py): relocates the Flask routing/glue code for the
Receiving workspace out of app.py. Business logic stays in
eoms_modules.receiving_service, unchanged.
"""

from flask import Blueprint, jsonify, render_template, request, session

from app import (
    STORES_FILE,
    ROUTES_FILE,
    read_json,
    write_json,
    synchronized_data_write,
    filter_stores_for_user,
    filter_routes_for_user,
    audit,
)
from eoms_modules.receiving_service import build_receiving_workspace, receive_load

receiving_bp = Blueprint("receiving", __name__)


@receiving_bp.route("/receiving")
def receiving_workspace():
    stores = filter_stores_for_user(read_json(STORES_FILE))
    routes = filter_routes_for_user(read_json(ROUTES_FILE))
    workspace = build_receiving_workspace(stores, routes)
    return render_template("receiving.html", workspace=workspace)


@receiving_bp.route("/api/receiving/receive", methods=["POST"])
@synchronized_data_write(STORES_FILE)
def api_receiving_receive():
    data = request.get_json(force=True) or {}
    stores = read_json(STORES_FILE)

    try:
        received = receive_load(
            stores,
            data.get("store_id"),
            received_by=session.get("username", "system"),
            warehouse_notes=data.get("warehouse_notes"),
            verified_racks=data.get("warehouse_verified_racks"),
            verified_pieces=data.get("warehouse_verified_pieces"),
            verified_counts=data.get("warehouse_verified_counts"),
            damage_counts=data.get("damage_counts"),
            damaged_material=data.get("damaged_material"),
            damage_notes=data.get("damage_notes"),
            warehouse_photos=data.get("warehouse_photos"),
        )
        already_received = bool(received.pop("already_received", False))
    except LookupError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    write_json(STORES_FILE, stores)
    routes = read_json(ROUTES_FILE)
    workspace = build_receiving_workspace(stores, routes)
    audit("Receive Recovery Load", {
        "store_id": received.get("id"),
        "bol": received.get("bol"),
        "already_received": already_received,
    })

    return jsonify({
        "ok": True,
        "already_received": already_received,
        "store": received,
        "next_load": workspace.get("selected_load"),
        "summary": workspace.get("summary", {}),
    })
