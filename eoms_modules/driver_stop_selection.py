"""Driver-owned stop selection and address-based pickup history."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from eoms_modules.driver_center_service import clean, store_ids_for_route, sync_route_stop_from_store, ACTIVE_DRIVER_STATUSES


def address_key(store):
    address = re.sub(r"[^a-z0-9]+", " ", clean(store.get("address")).lower()).strip()
    street_terms = {"st":"street", "rd":"road", "dr":"drive", "hwy":"highway", "ave":"avenue", "blvd":"boulevard", "ln":"lane", "ct":"court", "pkwy":"parkway"}
    address = " ".join(street_terms.get(word, word) for word in address.split())
    city = re.sub(r"[^a-z0-9]+", " ", clean(store.get("city")).lower()).strip()
    state = clean(store.get("state")).upper()
    zip_code = re.sub(r"\D", "", clean(store.get("zip")))[:5]
    # Require a street and locality; never match stores by name alone.
    return (address, city, state, zip_code) if address and city and state else None


def service_history(stop, stores):
    key = address_key(stop)
    visits = []
    for row in stores:
        if not key or row.get("id") == stop.get("id") or address_key(row) != key:
            continue
        if clean(row.get("status")).lower() not in {"recovered", "completed", "closed"} or row.get("driver_exception_type") in {"No Pickup", "No Recovery"}:
            continue
        try:
            completed = datetime.fromisoformat(clean(row.get("completed_at")).replace("Z", "+00:00"))
            if completed.tzinfo is None:
                continue
            visits.append(completed)
        except ValueError:
            continue
    if not visits:
        return "No service history yet"
    latest = max(visits).astimezone(ZoneInfo("America/Chicago"))
    days = (datetime.now(ZoneInfo("America/Chicago")).date() - latest.date()).days
    return "Last serviced: " + latest.strftime("%b %d, %Y") + (" · Today" if days == 0 else f" · {days} days ago")


def select_driver_stop(routes, stores, route_id, store_id, driver_names):
    route = next((row for row in routes if clean(row.get("id")) == clean(route_id)), None)
    if not route:
        raise LookupError("Route not found.")
    names = {clean(name) for name in driver_names if clean(name)}
    if names and clean(route.get("driver")) not in names:
        raise PermissionError("This route is not assigned to you.")
    if route.get("driver_status") != "Accepted":
        raise ValueError("Accept the route before choosing a pickup.")
    ids = set(store_ids_for_route(route))
    chosen = next((row for row in stores if clean(row.get("id")) == clean(store_id) and clean(store_id) in ids), None)
    if not chosen:
        raise LookupError("Pickup not found on this route.")
    if names and clean(chosen.get("assigned_driver")) not in names:
        raise PermissionError("This pickup is not assigned to you.")
    if clean(chosen.get("status")).lower() not in ACTIVE_DRIVER_STATUSES:
        raise ValueError("This pickup is already completed or unavailable.")
    for row in stores:
        if clean(row.get("id")) in ids and clean(row.get("status")).lower() in ACTIVE_DRIVER_STATUSES:
            row["driver_work_status"] = "Current" if row is chosen else "Waiting"
            row["status"] = "Dispatched" if row is chosen else "Assigned"
            sync_route_stop_from_store(route, row)
    return chosen
