"""Dispatcher Closeout workspace blueprint.

FT6 blueprint split (same pattern as driver_portal.py / receiving.py):
relocates Flask routing/glue code out of app.py. Business logic stays in
eoms_modules.dispatcher_closeout_service (and inventory_service, which the
closeout action also refreshes), unchanged.
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
    dispatch_required,
    audit,
)
from eoms_modules.dispatcher_closeout_service import (
    build_closeout_workspace,
    closeout_store,
    refresh_route_closeout,
)
from eoms_modules.inventory_service import build_inventory_workspace

dispatcher_closeout_bp = Blueprint("dispatcher_closeout", __name__)


@dispatcher_closeout_bp.route("/dispatcher-closeout")
@dispatch_required
def dispatcher_closeout_workspace():
    stores = filter_stores_for_user(read_json(STORES_FILE))
    routes = filter_routes_for_user(read_json(ROUTES_FILE))
    workspace = build_closeout_workspace(stores, routes)
    return render_template("dispatcher_closeout.html", workspace=workspace)


@dispatcher_closeout_bp.route("/api/dispatcher/closeout", methods=["POST"])
@dispatch_required
@synchronized_data_write(STORES_FILE, ROUTES_FILE)
def api_dispatcher_closeout():
    data = request.get_json(force=True) or {}
    stores = read_json(STORES_FILE)
    routes = read_json(ROUTES_FILE)

    try:
        closed = closeout_store(
            stores,
            data.get("store_id"),
            closed_by=session.get("username", "system"),
            notes=data.get("dispatcher_closeout_notes"),
        )
        already_closed = bool(closed.get("already_closed"))
        updated_routes = [] if already_closed else refresh_route_closeout(routes, stores, closed.get("id"))
    except LookupError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    write_json(STORES_FILE, stores)
    write_json(ROUTES_FILE, routes)
    workspace = build_inventory_workspace(stores)
    closeout_workspace = build_closeout_workspace(stores, routes)
    audit("Dispatcher Close-Out", {
        "store_id": closed.get("id"),
        "bol": closed.get("bol"),
        "inventory_source": closed.get("inventory_source"),
        "already_closed": already_closed,
    })

    return jsonify({
        "ok": True,
        "already_closed": already_closed,
        "store": closed,
        "next_load": closeout_workspace.get("selected_load"),
        "updated_routes": len(updated_routes),
        "inventory_summary": workspace.get("summary", {}),
    })
