from datetime import datetime, timezone

from eoms_modules.recovery_center_service import (
    COMPONENT_NAMES,
    COMPONENT_WEIGHTS,
    STORE_COMPONENT_FIELDS,
    calculate_estimated_weight,
    clean,
    empty_component_counts,
    normalize_quantity,
)
from eoms_modules.receiving_service import RECEIVED_STATUS, is_received_store
from eoms_modules.receiving_service import (
    DAMAGE_CATEGORIES,
    DISPATCHER_CLOSED_STATUS,
    damage_counts_from_store,
    warehouse_verified_counts_from_store,
)


WAREHOUSE_CAPACITY_COMPONENTS = 25000


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_adjustment_amount(value):
    if value in (None, ""):
        raise ValueError("Adjustment amount is required.")

    try:
        amount = int(float(value))
    except (TypeError, ValueError):
        raise ValueError("Adjustment amount must be a whole number.")

    if amount == 0:
        raise ValueError("Adjustment amount cannot be zero.")

    return amount


def received_stores(stores=None):
    return [
        store for store in stores or []
        if (
            isinstance(store, dict)
            and is_received_store(store)
            and clean(store.get("dispatcher_closeout_status")) == DISPATCHER_CLOSED_STATUS
        )
    ]


def receipt_counts_for_store(store):
    if store not in received_stores([store]):
        return empty_component_counts()
    if not isinstance(store.get("warehouse_verified_counts"), dict):
        return empty_component_counts()
    return warehouse_verified_counts_from_store(store)


def inventory_transaction_id(store):
    return clean(store.get("inventory_transaction_id")) or f"INV-{clean(store.get('id') or store.get('bol'))}"


def inventory_receipt_transactions(stores=None):
    transactions = []

    for store in received_stores(stores):
        counts = receipt_counts_for_store(store)
        damage_counts = damage_counts_from_store(store)
        transaction_id = inventory_transaction_id(store)

        for component in COMPONENT_NAMES:
            verified_quantity = counts.get(component, 0)
            assigned_damage = 0
            for category in DAMAGE_CATEGORIES:
                if category == "Good Inventory":
                    continue
                quantity = damage_counts[category].get(component, 0)
                if quantity:
                    transactions.append({
                        "transaction_id": f"{transaction_id}:{category}:{component}",
                        "bol": clean(store.get("bol")) or "Not set",
                        "store": clean(store.get("store_name") or store.get("store")) or "Unknown Store",
                        "component": component,
                        "category": category,
                        "quantity": quantity,
                        "dispatcher_approval": clean(store.get("dispatcher_closed_by")) or "system",
                        "dispatcher_approved_at": clean(store.get("dispatcher_closed_at")),
                        "warehouse_verification": clean(store.get("received_by")) or "system",
                        "warehouse_verified_at": clean(store.get("received_at")),
                        "inventory_updated_at": clean(store.get("inventory_updated_at") or store.get("dispatcher_closed_at")),
                        "inventory_updated_by": clean(store.get("inventory_updated_by") or store.get("dispatcher_closed_by")),
                    })
                assigned_damage += quantity

            good_quantity = max(0, verified_quantity - assigned_damage)
            if good_quantity:
                transactions.append({
                    "transaction_id": f"{transaction_id}:Good Inventory:{component}",
                    "bol": clean(store.get("bol")) or "Not set",
                    "store": clean(store.get("store_name") or store.get("store")) or "Unknown Store",
                    "component": component,
                    "category": "Good Inventory",
                    "quantity": good_quantity,
                    "dispatcher_approval": clean(store.get("dispatcher_closed_by")) or "system",
                    "dispatcher_approved_at": clean(store.get("dispatcher_closed_at")),
                    "warehouse_verification": clean(store.get("received_by")) or "system",
                    "warehouse_verified_at": clean(store.get("received_at")),
                    "inventory_updated_at": clean(store.get("inventory_updated_at") or store.get("dispatcher_closed_at")),
                    "inventory_updated_by": clean(store.get("inventory_updated_by") or store.get("dispatcher_closed_by")),
                })

    return sorted(transactions, key=lambda item: item["inventory_updated_at"], reverse=True)


def adjustment_entries(stores=None):
    entries = []

    for store in stores or []:
        if not isinstance(store, dict):
            continue

        for entry in store.get("inventory_adjustments") or []:
            if not isinstance(entry, dict):
                continue

            component = clean(entry.get("component"))
            if component not in COMPONENT_NAMES:
                continue

            try:
                amount = int(float(entry.get("amount", 0)))
            except (TypeError, ValueError):
                amount = 0

            entries.append({
                "component": component,
                "amount": amount,
                "reason": clean(entry.get("reason")) or "Adjustment",
                "adjusted_by": clean(entry.get("adjusted_by")) or "system",
                "adjusted_at": clean(entry.get("adjusted_at")),
                "store": clean(store.get("store_name") or store.get("store")) or "Warehouse",
                "bol": clean(store.get("bol")) or "Not set",
            })

    return sorted(entries, key=lambda entry: entry["adjusted_at"], reverse=True)


def component_receipt_history(stores=None, component=""):
    component = clean(component)
    history = []

    if component not in COMPONENT_NAMES:
        return history

    for store in received_stores(stores):
        for transaction in inventory_receipt_transactions([store]):
            if transaction["component"] != component:
                continue
            history.append({
                "type": "Warehouse Verified Receipt",
                "store": transaction["store"],
                "bol": transaction["bol"],
                "quantity": transaction["quantity"],
                "category": transaction["category"],
                "date": transaction["inventory_updated_at"] or transaction["dispatcher_approved_at"] or "Not set",
                "operator": transaction["inventory_updated_by"] or transaction["dispatcher_approval"] or "Not recorded",
                "warehouse_verified_at": transaction["warehouse_verified_at"],
                "dispatcher_approved_at": transaction["dispatcher_approved_at"],
            })

    return sorted(history, key=lambda entry: entry["date"], reverse=True)


def component_adjustment_history(stores=None, component=""):
    component = clean(component)
    return [
        entry for entry in adjustment_entries(stores)
        if entry["component"] == component
    ]


def adjustment_totals(stores=None):
    totals = empty_component_counts()

    for entry in adjustment_entries(stores):
        totals[entry["component"]] += entry["amount"]

    return totals


def receipt_totals(stores=None):
    totals = empty_component_counts()

    for store in received_stores(stores):
        counts = receipt_counts_for_store(store)
        for component in COMPONENT_NAMES:
            totals[component] += counts[component]

    return totals


def inventory_totals(stores=None):
    receipts = receipt_totals(stores)
    adjustments = adjustment_totals(stores)
    totals = empty_component_counts()

    for component in COMPONENT_NAMES:
        totals[component] = max(0, receipts[component] + adjustments[component])

    return totals


def category_inventory_totals(stores=None):
    totals = {
        category: empty_component_counts()
        for category in DAMAGE_CATEGORIES
    }

    for store in received_stores(stores):
        verified_counts = receipt_counts_for_store(store)
        damage_counts = damage_counts_from_store(store)

        assigned = empty_component_counts()
        for category in DAMAGE_CATEGORIES:
            if category == "Good Inventory":
                continue
            for component in COMPONENT_NAMES:
                value = damage_counts[category].get(component, 0)
                totals[category][component] += value
                assigned[component] += value

        for component in COMPONENT_NAMES:
            totals["Good Inventory"][component] += max(0, verified_counts.get(component, 0) - assigned[component])

    return totals


def build_component_row(component, quantity, reserved=0):
    reserved = max(0, int(reserved or 0))
    available = max(0, quantity - reserved)

    return {
        "component": component,
        "quantity": quantity,
        "weight": round(quantity * COMPONENT_WEIGHTS[component], 2),
        "available": available,
        "reserved": reserved,
        "last_updated": "",
    }


def latest_component_update(stores=None, component=""):
    dates = []

    for entry in component_receipt_history(stores, component):
        if entry["date"] != "Not set":
            dates.append(entry["date"])

    for entry in component_adjustment_history(stores, component):
        if entry["adjusted_at"]:
            dates.append(entry["adjusted_at"])

    return max(dates) if dates else "Not updated"


def build_inventory_rows(stores=None):
    totals = inventory_totals(stores)
    rows = []

    for component in COMPONENT_NAMES:
        row = build_component_row(component, totals[component])
        row["last_updated"] = latest_component_update(stores, component)
        rows.append(row)

    return rows


def build_inventory_history(stores=None):
    history = []

    for component in COMPONENT_NAMES:
        running_total = 0

        component_events = []
        for receipt in component_receipt_history(stores, component):
            component_events.append({
                "type": "Receipt",
                "component": component,
                "amount": receipt["quantity"],
                "date": receipt["date"],
                "operator": receipt["operator"],
                "reason": f"{receipt['store']} / {receipt['bol']} / {receipt.get('category', 'Inventory')}",
                "category": receipt.get("category", "Inventory"),
                "bol": receipt.get("bol"),
                "warehouse_verified_at": receipt.get("warehouse_verified_at"),
                "dispatcher_approved_at": receipt.get("dispatcher_approved_at"),
            })

        for adjustment in component_adjustment_history(stores, component):
            component_events.append({
                "type": "Adjustment",
                "component": component,
                "amount": adjustment["amount"],
                "date": adjustment["adjusted_at"] or "Not set",
                "operator": adjustment["adjusted_by"],
                "reason": adjustment["reason"],
                "category": "Adjustment",
                "bol": adjustment.get("bol"),
            })

        for event in sorted(component_events, key=lambda item: item["date"]):
            running_total = max(0, running_total + event["amount"])
            event["running_total"] = running_total
            history.append(event)

    return sorted(history, key=lambda item: item["date"], reverse=True)


def build_inventory_summary(rows):
    total_components = sum(row["quantity"] for row in rows)
    reserved_inventory = sum(row["reserved"] for row in rows)
    available_inventory = sum(row["available"] for row in rows)
    inventory_weight = sum(row["weight"] for row in rows)
    capacity_percent = 0

    if WAREHOUSE_CAPACITY_COMPONENTS:
        capacity_percent = round(min(100, (total_components / WAREHOUSE_CAPACITY_COMPONENTS) * 100), 1)

    return {
        "total_components": total_components,
        "available_inventory": available_inventory,
        "reserved_inventory": reserved_inventory,
        "inventory_weight": round(inventory_weight, 2),
        "warehouse_capacity": WAREHOUSE_CAPACITY_COMPONENTS,
        "warehouse_capacity_used": capacity_percent,
    }


def build_inventory_categories(stores=None):
    category_totals = category_inventory_totals(stores)
    categories = []

    for category in DAMAGE_CATEGORIES:
        component_counts = category_totals[category]
        quantity = sum(component_counts.values())
        categories.append({
            "category": category,
            "quantity": quantity,
            "weight": calculate_estimated_weight(component_counts),
            "components": component_counts,
        })

    return categories


def build_inventory_detail(stores=None, component=""):
    component = clean(component) or COMPONENT_NAMES[0]
    if component not in COMPONENT_NAMES:
        component = COMPONENT_NAMES[0]

    totals = inventory_totals(stores)
    quantity = totals[component]

    return {
        "component": component,
        "current_quantity": quantity,
        "weight": round(quantity * COMPONENT_WEIGHTS[component], 2),
        "last_updated": latest_component_update(stores, component),
        "receiving_history": component_receipt_history(stores, component),
        "adjustments": component_adjustment_history(stores, component),
    }


def build_inventory_workspace(stores=None, selected_component=""):
    stores = stores if isinstance(stores, list) else []
    rows = build_inventory_rows(stores)

    return {
        "component_names": COMPONENT_NAMES,
        "summary": build_inventory_summary(rows),
        "categories": build_inventory_categories(stores),
        "inventory": rows,
        "detail": build_inventory_detail(stores, selected_component),
        "history": build_inventory_history(stores),
        "transactions": inventory_receipt_transactions(stores),
    }


def validate_adjustment(stores, component, amount, reason):
    if not isinstance(stores, list):
        raise ValueError("Stores must be provided as a list.")

    component = clean(component)
    if component not in COMPONENT_NAMES:
        raise ValueError("A valid component is required.")

    amount = normalize_adjustment_amount(amount)
    reason = clean(reason)
    if not reason:
        raise ValueError("Adjustment reason is required.")

    candidate_stores = received_stores(stores)
    if not candidate_stores:
        raise ValueError("Inventory adjustments require at least one received load.")

    current_quantity = inventory_totals(stores)[component]
    if current_quantity + amount < 0:
        raise ValueError("Adjustment would make inventory negative.")

    target_store = sorted(
        candidate_stores,
        key=lambda store: clean(store.get("received_at")) or clean(store.get("completed_at")),
        reverse=True,
    )[0]

    return target_store, component, amount, reason


def adjust_inventory(stores, component, amount, reason, adjusted_by=""):
    target_store, component, amount, reason = validate_adjustment(stores, component, amount, reason)
    adjustment = {
        "component": component,
        "amount": amount,
        "reason": reason,
        "adjusted_by": clean(adjusted_by) or "system",
        "adjusted_at": utc_now_iso(),
    }

    adjustments = target_store.setdefault("inventory_adjustments", [])
    if not isinstance(adjustments, list):
        target_store["inventory_adjustments"] = []
        adjustments = target_store["inventory_adjustments"]
    adjustments.append(adjustment)

    return adjustment
