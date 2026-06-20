import csv
import json
import math
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import Flask, jsonify, redirect, render_template, request, url_for
from openpyxl import load_workbook
from werkzeug.utils import secure_filename

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"

STORES_FILE = DATA_DIR / "stores.json"
ROUTES_FILE = DATA_DIR / "routes.json"
AUDIT_FILE = DATA_DIR / "audit_log.json"

MAX_PAYLOAD = 25001
PIECES_PER_RACK = 19
DEFAULT_RACK_WEIGHT = 200

HUBS = {
    "San Antonio": {
        "lat": 29.4241,
        "lng": -98.4936,
        "address": "San Antonio, TX"
    },
    "Houston": {
        "lat": 29.7604,
        "lng": -95.3698,
        "address": "Houston, TX"
    },
    "Dallas": {
        "lat": 32.7767,
        "lng": -96.7970,
        "address": "8101 Tristar Drive, Suite 112, Irving, TX 75063"
    }
}

CITY_COORDS = {
    "San Antonio": (29.4241, -98.4936),
    "Houston": (29.7604, -95.3698),
    "Dallas": (32.7767, -96.7970),
    "Irving": (32.8140, -96.9489),
    "Killeen": (31.1171, -97.7278),
    "Austin": (30.2672, -97.7431),
    "Waco": (31.5493, -97.1467),
    "San Marcos": (29.8833, -97.9414),
    "New Braunfels": (29.7030, -98.1245),
    "Selma": (29.5844, -98.3058),
    "Kyle": (29.9891, -97.8772),
    "Corpus Christi": (27.8006, -97.3964),
    "Brownsville": (25.9017, -97.4975),
    "McAllen": (26.2034, -98.2300),
    "Beaumont": (30.0802, -94.1266),
    "Abilene": (32.4487, -99.7331),
    "Fort Worth": (32.7555, -97.3308),
    "Lubbock": (33.5779, -101.8552)
}

def ensure_files():
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    for path, default in [
        (STORES_FILE, []),
        (ROUTES_FILE, []),
        (AUDIT_FILE, [])
    ]:
        if not path.exists():
            path.write_text(json.dumps(default, indent=2), encoding="utf-8")

def read_json(path):
    ensure_files()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

def write_json(path, data):
    ensure_files()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def audit(action, details):
    log = read_json(AUDIT_FILE)
    log.append({
        "id": str(uuid4()),
        "time": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "details": details
    })
    write_json(AUDIT_FILE, log)

def clean(value):
    if value is None:
        return ""
    return str(value).strip()

def num(value, default=0):
    try:
        if value in [None, ""]:
            return default
        return float(str(value).replace(",", "").strip())
    except Exception:
        return default

def miles_between(lat1, lng1, lat2, lng2):
    radius = 3958.8
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def coords_for(city, state):
    city = clean(city)
    if city in CITY_COORDS:
        lat, lng = CITY_COORDS[city]
        return lat, lng
    return 30.2672, -97.7431

def assign_hub(lat, lng, dispatch_group=""):
    group = clean(dispatch_group).lower()
    if "houston" in group:
        return "Houston", "Dispatch Group"
    if "san antonio" in group or group == "sa":
        return "San Antonio", "Dispatch Group"
    if "dallas" in group or "irving" in group:
        return "Dallas", "Dispatch Group"

    nearest = None
    nearest_miles = 999999
    for hub_name, hub in HUBS.items():
        miles = miles_between(lat, lng, hub["lat"], hub["lng"])
        if miles < nearest_miles:
            nearest = hub_name
            nearest_miles = miles

    if nearest_miles <= 100:
        return nearest, f"Nearest Hub {round(nearest_miles, 1)} mi"
    return "Manual Review", f"Outside 100 mi ({round(nearest_miles, 1)} mi)"

def normalize_row(row):
    bol = clean(row.get("BOL #") or row.get("BOL") or row.get("BOL Number"))
    origin = clean(row.get("Origin") or row.get("Store") or row.get("Store Name"))
    store_name = clean(row.get("Store Name")) or origin or f"BOL {bol}"
    city = clean(row.get("City") or row.get("Origin City"))
    state = clean(row.get("State") or row.get("Origin State")) or "TX"
    address = clean(row.get("Origin Address") or row.get("Carrier Address") or row.get("Address"))
    dispatch_group = clean(row.get("Dispatch Group") or row.get("Route"))

    racks = num(row.get("Est Racks") or row.get("Expected Racks") or row.get("Racks"))
    if not racks:
        pieces = (
            num(row.get('84" Corner Post Only')) +
            num(row.get('40" DRB')) +
            num(row.get('48" DRB')) +
            num(row.get("Wood Shelf"))
        )
        racks = round(pieces / PIECES_PER_RACK, 2) if pieces else 0

    lat, lng = coords_for(city, state)
    hub, hub_reason = assign_hub(lat, lng, dispatch_group)

    return {
        "id": str(uuid4()),
        "bol": bol,
        "origin": origin,
        "store_name": store_name,
        "address": address,
        "city": city,
        "state": state,
        "lat": lat,
        "lng": lng,
        "hub": hub,
        "hub_reason": hub_reason,
        "dispatch_group": dispatch_group,
        "expected_racks": racks,
        "weight": round(racks * DEFAULT_RACK_WEIGHT, 2),
        "status": "Unassigned",
        "assigned_driver": "",
        "created_at": datetime.now().isoformat(timespec="seconds")
    }

def parse_xlsx(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    sheet_name = "BOL_Intake" if "BOL_Intake" in wb.sheetnames else wb.sheetnames[0]
    ws = wb[sheet_name]
    headers = [clean(ws.cell(1, c).value) for c in range(1, ws.max_column + 1)]
    rows = []
    for r in range(2, ws.max_row + 1):
        raw = {}
        has_data = False
        for c, header in enumerate(headers, start=1):
            value = ws.cell(r, c).value
            if value not in [None, ""]:
                has_data = True
            raw[header] = value
        if has_data:
            rows.append(normalize_row(raw))
    return rows

def parse_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(normalize_row(row))
    return rows

@app.route("/")
def home():
    return render_template("login.html")

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/dispatch-map")
def dispatch_map():
    stores = read_json(STORES_FILE)
    return render_template(
        "dispatch_map.html",
        stores=stores,
        hubs=HUBS,
        max_payload=MAX_PAYLOAD
    )

@app.route("/rms-import", methods=["GET", "POST"])
def rms_import():
    if request.method == "POST":
        uploaded = request.files.get("rms_file")
        if not uploaded or uploaded.filename == "":
            return render_template("rms_import.html", message="Choose an RMS export file first.")

        filename = secure_filename(uploaded.filename)
        path = UPLOAD_DIR / filename
        uploaded.save(path)

        if filename.lower().endswith(".xlsx"):
            imported = parse_xlsx(path)
        elif filename.lower().endswith(".csv"):
            imported = parse_csv(path)
        else:
            return render_template("rms_import.html", message="Only .xlsx and .csv files are supported right now.")

        existing = read_json(STORES_FILE)
        existing_keys = {(s.get("bol"), s.get("origin")) for s in existing}

        added = 0
        duplicates = 0

        for item in imported:
            key = (item.get("bol"), item.get("origin"))
            if key in existing_keys:
                duplicates += 1
                continue
            existing.append(item)
            existing_keys.add(key)
            added += 1

        write_json(STORES_FILE, existing)
        audit("RMS Import", {"file": filename, "added": added, "duplicates": duplicates})

        return render_template(
            "rms_import.html",
            message=f"Import complete. Added {added}. Skipped duplicates {duplicates}."
        )

    return render_template("rms_import.html", message="")

@app.route("/api/assign-route", methods=["POST"])
def api_assign_route():
    data = request.get_json(force=True)
    driver = clean(data.get("driver"))
    store_ids = data.get("store_ids", [])

    stores = read_json(STORES_FILE)
    assigned = []

    for store in stores:
        if store["id"] in store_ids and store["status"] == "Unassigned":
            store["status"] = "Assigned"
            store["assigned_driver"] = driver
            assigned.append(store)

    route = {
        "id": str(uuid4()),
        "driver": driver,
        "store_ids": store_ids,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "Assigned"
    }

    routes = read_json(ROUTES_FILE)
    routes.append(route)

    write_json(STORES_FILE, stores)
    write_json(ROUTES_FILE, routes)
    audit("Assign Route", {"driver": driver, "stores": len(assigned)})

    return jsonify({"ok": True, "route": route, "assigned": assigned})

@app.route("/api/unassign-store", methods=["POST"])
def api_unassign_store():
    data = request.get_json(force=True)
    store_id = data.get("store_id")

    stores = read_json(STORES_FILE)
    restored = None

    for store in stores:
        if store["id"] == store_id:
            store["status"] = "Unassigned"
            store["assigned_driver"] = ""
            restored = store
            break

    write_json(STORES_FILE, stores)
    audit("Unassign Store", {"store_id": store_id})

    return jsonify({"ok": True, "store": restored})

@app.route("/driver")
def driver_portal():
    stores = [s for s in read_json(STORES_FILE) if s.get("status") == "Assigned"]
    return render_template("driver.html", stores=stores)

@app.route("/api/driver/complete", methods=["POST"])
def api_driver_complete():
    data = request.get_json(force=True)
    store_id = data.get("store_id")
    collected_racks = num(data.get("collected_racks"))

    stores = read_json(STORES_FILE)
    updated = None
    for store in stores:
        if store["id"] == store_id:
            store["collected_racks"] = collected_racks
            store["variance"] = collected_racks - num(store.get("expected_racks"))
            store["status"] = "Completed"
            updated = store
            break

    write_json(STORES_FILE, stores)
    audit("Driver Complete", {"store_id": store_id, "collected_racks": collected_racks})

    return jsonify({"ok": True, "store": updated})

if __name__ == "__main__":
    ensure_files()
    app.run(debug=True)
