from datetime import datetime, timezone

from eoms_modules.inventory_service import inventory_totals, received_stores
from eoms_modules.recovery_center_service import (
    COMPONENT_NAMES,
    COMPONENT_WEIGHTS,
    calculate_estimated_weight,
    clean,
    empty_component_counts,
    normalize_quantity,
)


OPEN_STATUSES = {"open", "reserved", "ready"}
SHIPPED_STATUS = "Shipped"
DEFAULT_STATUS = "Reserved"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_order_number(value):
    return clean(value) or f"FUL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


def normalize_component_counts(payload=None):
    payload = payload or {}
    counts = empty_component_counts()

    for component in COMPONENT_NAMES:
        counts[component] = normalize_quantity(payload.get(component, 0), component)

    return counts


def order_component_weight(component_counts):
    return calculate_estimated_weight(component_counts)


def ensure_order_list(store):
    orders = store.setdefault("fulfillment_orders", [])
    if not isinstance(orders, list):
        store["fulfillment_orders"] = []
        orders = store["fulfillment_orders"]
    return orders


def fulfillment_orders(stores=None):
    orders = []

    for store in stores or []:
        if not isinstance(store, dict):
            continue

        source_label = clean(store.get("store_name") or store.get("store")) or "Warehouse Stock"
        source_bol = clean(store.get("bol")) or "Not set"

        for order in store.get("fulfillment_orders") or []:
            if not isinstance(order, dict):
                continue

            component_counts = normalize_component_counts(order.get("reserved_components"))
            order_status = clean(order.get("status")) or DEFAULT_STATUS
            orders.append({
                "order_number": clean(order.get("order_number")) or "Unnumbered",
                "customer": clean(order.get("customer")) or "Unassigned Customer",
                "status": order_status,
                "status_class": fulfillment_status_class(order_status),
                "reserved_components": component_counts,
                "reserved_quantity": sum(component_counts.values()),
                "weight": order_component_weight(component_counts),
                "inventory_source": f"{source_label} / {source_bol}",
                "reserved_by": clean(order.get("reserved_by")) or "Not recorded",
                "reserved_at": clean(order.get("reserved_at")),
                "shipped_by": clean(order.get("shipped_by")),
                "shipped_at": clean(order.get("shipped_at")),
                "shipment_notes": clean(order.get("shipment_notes")),
            })

    return sorted(orders, key=lambda order: order["reserved_at"], reverse=True)


def fulfillment_status_class(status):
    status = clean(status).lower()
    if status == "shipped":
        return "success"
    if status in {"ready", "reserved"}:
        return "warning"
    if status in {"blocked", "cancelled"}:
        return "danger"
    return "neutral"


def active_reservation_totals(stores=None):
    totals = empty_component_counts()

    for order in fulfillment_orders(stores):
        if clean(order["status"]).lower() not in OPEN_STATUSES:
            continue

        for component in COMPONENT_NAMES:
            totals[component] += order["reserved_components"][component]

    return totals


def shipped_totals(stores=None):
    totals = empty_component_counts()

    for order in fulfillment_orders(stores):
        if clean(order["status"]) != SHIPPED_STATUS:
            continue

        for component in COMPONENT_NAMES:
            totals[component] += order["reserved_components"][component]

    return totals


def available_inventory(stores=None):
    totals = inventory_totals(stores)
    reserved = active_reservation_totals(stores)
    shipped = shipped_totals(stores)
    available = empty_component_counts()

    for component in COMPONENT_NAMES:
        available[component] = max(0, totals[component] - reserved[component] - shipped[component])

    return available


def build_fulfillment_summary(stores=None, orders=None):
    orders = orders if orders is not None else fulfillment_orders(stores)
    open_orders = [order for order in orders if clean(order["status"]).lower() in OPEN_STATUSES]
    ready_orders = [order for order in orders if clean(order["status"]).lower() == "ready"]
    shipped_orders = [order for order in orders if clean(order["status"]) == SHIPPED_STATUS]
    reserved_totals = active_reservation_totals(stores)
    shipped_weight = sum(order["weight"] for order in shipped_orders)
    outbound_weight = sum(order["weight"] for order in open_orders) + shipped_weight

    return {
        "open_orders": len(open_orders),
        "orders_ready": len(ready_orders),
        "orders_shipped": len(shipped_orders),
        "components_reserved": sum(reserved_totals.values()),
        "outbound_weight": round(outbound_weight, 2),
    }


def build_order_detail(orders=None, order_number=""):
    orders = orders or []
    order_number = clean(order_number)

    if order_number:
        for order in orders:
            if clean(order["order_number"]) == order_number:
                return order

    return orders[0] if orders else None


def build_fulfillment_history(stores=None):
    history = []
    running_reserved = 0
    running_shipped = 0

    events = []
    for order in fulfillment_orders(stores):
        events.append({
            "type": "Reservation",
            "order_number": order["order_number"],
            "customer": order["customer"],
            "amount": order["reserved_quantity"],
            "date": order["reserved_at"] or "Not set",
            "operator": order["reserved_by"],
            "status": order["status"],
        })

        if clean(order["status"]) == SHIPPED_STATUS:
            events.append({
                "type": "Shipment",
                "order_number": order["order_number"],
                "customer": order["customer"],
                "amount": order["reserved_quantity"],
                "date": order["shipped_at"] or "Not set",
                "operator": order["shipped_by"] or "Not recorded",
                "status": SHIPPED_STATUS,
            })

    for event in sorted(events, key=lambda item: item["date"]):
        if event["type"] == "Reservation":
            running_reserved += event["amount"]
        if event["type"] == "Shipment":
            running_shipped += event["amount"]
        event["running_reserved"] = running_reserved
        event["running_shipped"] = running_shipped
        history.append(event)

    return sorted(history, key=lambda item: item["date"], reverse=True)


def build_fulfillment_workspace(stores=None, selected_order=""):
    stores = stores if isinstance(stores, list) else []
    orders = fulfillment_orders(stores)

    return {
        "component_names": COMPONENT_NAMES,
        "summary": build_fulfillment_summary(stores, orders),
        "orders": orders,
        "detail": build_order_detail(orders, selected_order),
        "available_inventory": available_inventory(stores),
        "history": build_fulfillment_history(stores),
    }


def reservation_payload(data=None):
    data = data or {}
    component = clean(data.get("component"))
    if component not in COMPONENT_NAMES:
        raise ValueError("A valid component is required.")

    quantity = normalize_quantity(data.get("quantity"), component)
    if quantity <= 0:
        raise ValueError("Reserved quantity must be greater than zero.")

    customer = clean(data.get("customer"))
    if not customer:
        raise ValueError("Customer is required.")

    return {
        "order_number": normalize_order_number(data.get("order_number")),
        "customer": customer,
        "component": component,
        "quantity": quantity,
    }


def reserve_inventory(stores, data=None, reserved_by=""):
    if not isinstance(stores, list):
        raise ValueError("Stores must be provided as a list.")

    payload = reservation_payload(data)
    available = available_inventory(stores)
    component = payload["component"]
    quantity = payload["quantity"]

    if quantity > available[component]:
        raise ValueError("Reservation cannot exceed available inventory.")

    candidates = received_stores(stores)
    if not candidates:
        raise ValueError("Reservations require received inventory.")

    target_store = sorted(
        candidates,
        key=lambda store: clean(store.get("received_at")) or clean(store.get("completed_at")),
        reverse=True,
    )[0]

    component_counts = empty_component_counts()
    component_counts[component] = quantity
    order = {
        "order_number": payload["order_number"],
        "customer": payload["customer"],
        "status": DEFAULT_STATUS,
        "reserved_components": component_counts,
        "reserved_by": clean(reserved_by) or "system",
        "reserved_at": utc_now_iso(),
        "reserved_quantity": quantity,
    }
    ensure_order_list(target_store).append(order)
    return order


def find_order_record(stores, order_number):
    order_number = clean(order_number)
    if not order_number:
        raise ValueError("Order number is required.")

    for store in stores or []:
        if not isinstance(store, dict):
            continue

        for order in store.get("fulfillment_orders") or []:
            if not isinstance(order, dict):
                continue
            if clean(order.get("order_number")) == order_number:
                return order

    raise LookupError("Fulfillment order was not found.")


def ship_order(stores, order_number, shipped_by="", shipment_notes=""):
    if not isinstance(stores, list):
        raise ValueError("Stores must be provided as a list.")

    order = find_order_record(stores, order_number)
    if clean(order.get("status")) == SHIPPED_STATUS:
        order["already_shipped"] = True
        return order

    component_counts = normalize_component_counts(order.get("reserved_components"))
    if sum(component_counts.values()) <= 0:
        raise ValueError("Order has no reserved components to ship.")

    order["status"] = SHIPPED_STATUS
    order["shipped_by"] = clean(shipped_by) or "system"
    order["shipped_at"] = utc_now_iso()
    order["shipment_notes"] = clean(shipment_notes)
    order["already_shipped"] = False
    return order
