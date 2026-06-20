import csv
import json
import math
import re
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import Flask, jsonify, render_template, request
from openpyxl import load_workbook
from pypdf import PdfReader
from werkzeug.utils import secure_filename

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
BOL_DIR = BASE_DIR / "bol_files"

STORES_FILE = DATA_DIR / "stores.json"
ROUTES_FILE = DATA_DIR / "routes.json"
AUDIT_FILE = DATA_DIR / "audit_log.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
SYNC_HISTORY_FILE = DATA_DIR / "sync_history.json"

MAX_PAYLOAD = 25001
WARNING_PAYLOAD = 22000
PIECES_PER_RACK = 19
RATE_PER_PIECE = 0.95
DRIVER_PAY_PER_PIECE = 0.30
DEFAULT_RACK_WEIGHT = 200

HUBS = {
    "San Antonio": {"lat": 29.4241, "lng": -98.4936, "address": "San Antonio, TX"},
    "Houston": {"lat": 29.7604, "lng": -95.3698, "address": "Houston, TX"},
    "Dallas": {"lat": 32.8140, "lng": -96.9489, "address": "8101 Tristar Drive, Suite 112, Irving, TX 75063"}
}

CITY_COORDS = {
    "San Antonio": (29.4241, -98.4936), "Houston": (29.7604, -95.3698),
    "Dallas": (32.7767, -96.7970), "Irving": (32.8140, -96.9489),
    "Killeen": (31.1171, -97.7278), "Austin": (30.2672, -97.7431),
    "Waco": (31.5493, -97.1467), "San Marcos": (29.8833, -97.9414),
    "New Braunfels": (29.7030, -98.1245), "Selma": (29.5844, -98.3058),
    "Kyle": (29.9891, -97.8772), "Corpus Christi": (27.8006, -97.3964),
    "Brownsville": (25.9017, -97.4975), "McAllen": (26.2034, -98.2300),
    "Beaumont": (30.0802, -94.1266), "Marble Falls": (30.5782, -98.2728),
    "Abilene": (32.4487, -99.7331), "Fort Worth": (32.7555, -97.3308),
    "Lubbock": (33.5779, -101.8552)
}

def ensure_dirs():
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    for root in ["Imported", "Assigned", "Completed", "Need_Review", "RMS_Backup"]:
        (BOL_DIR / root).mkdir(parents=True, exist_ok=True)
    for path, default in [
        (STORES_FILE, []), (ROUTES_FILE, []), (AUDIT_FILE, []),
        (SETTINGS_FILE, {"rms_username": "", "rms_password_saved": False, "rms_login_url": "https://rms.reusability.com/login", "rms_bol_url": "https://rms.reusability.com/bills-of-lading"}),
        (SYNC_HISTORY_FILE, [])
    ]:
        if not path.exists():
            path.write_text(json.dumps(default, indent=2), encoding="utf-8")

def read_json(path):
    ensure_dirs()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [] if path != SETTINGS_FILE else {}

def write_json(path, data):
    ensure_dirs()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def audit(action, details):
    log = read_json(AUDIT_FILE)
    log.append({"id": str(uuid4()), "time": datetime.now().isoformat(timespec="seconds"), "action": action, "details": details})
    write_json(AUDIT_FILE, log)

def clean(value):
    return "" if value is None else str(value).strip()

def num(value, default=0):
    try:
        if value in [None, ""]:
            return default
        return float(str(value).replace(",", "").strip())
    except Exception:
        return default

def safe_part(value):
    value = re.sub(r"[^A-Za-z0-9_-]+", "", clean(value).replace(" ", ""))
    return value[:35] or "Unknown"

def month_folder(root, when=None):
    when = when or datetime.now()
    folder = BOL_DIR / root / str(when.year) / f"{when.month:02d}_{when.strftime('%B')}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder

def move_pdf(current_path, destination_root):
    current = Path(current_path)
    if not current.exists():
        return str(current_path)
    dest = month_folder(destination_root) / current.name
    if dest.exists():
        dest = dest.with_name(dest.stem + "_" + datetime.now().strftime("%H%M%S") + dest.suffix)
    shutil.move(str(current), str(dest))
    return str(dest)

def miles_between(lat1, lng1, lat2, lng2):
    radius = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lng2-lng1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return radius * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))


def route_miles(points):
    if len(points) < 2:
        return 0
    total = 0
    for i in range(len(points) - 1):
        total += miles_between(points[i]["lat"], points[i]["lng"], points[i+1]["lat"], points[i+1]["lng"])
    return round(total, 1)

def order_nearest_from_hub(hub_name, selected_stores):
    hub = HUBS.get(hub_name) or HUBS["San Antonio"]
    current = {"lat": hub["lat"], "lng": hub["lng"]}
    remaining = selected_stores[:]
    ordered = []
    while remaining:
        next_stop = min(remaining, key=lambda s: miles_between(current["lat"], current["lng"], num(s.get("lat")), num(s.get("lng"))))
        ordered.append(next_stop)
        remaining.remove(next_stop)
        current = {"lat": num(next_stop.get("lat")), "lng": num(next_stop.get("lng"))}
    return ordered

def calculate_route_metrics(ordered_stores, hub_name):
    hub = HUBS.get(hub_name) or HUBS["San Antonio"]
    points = [{"lat": hub["lat"], "lng": hub["lng"]}]
    for s in ordered_stores:
        points.append({"lat": num(s.get("lat")), "lng": num(s.get("lng"))})
    points.append({"lat": hub["lat"], "lng": hub["lng"]})

    racks = sum(num(s.get("expected_racks")) for s in ordered_stores)
    pieces = racks * PIECES_PER_RACK
    weight = sum(num(s.get("weight")) for s in ordered_stores)
    remaining = MAX_PAYLOAD - weight
    status = "OVER LIMIT" if weight > MAX_PAYLOAD else ("WARNING" if weight > WARNING_PAYLOAD else "SAFE")

    return {
        "hub": hub_name,
        "store_count": len(ordered_stores),
        "racks": round(racks, 2),
        "pieces": round(pieces, 2),
        "weight": round(weight, 2),
        "remaining_capacity": round(remaining, 2),
        "mileage": route_miles(points),
        "revenue": round(pieces * RATE_PER_PIECE, 2),
        "driver_pay": round(pieces * DRIVER_PAY_PER_PIECE, 2),
        "status": status
    }

def build_route_order(store_ids, mode):
    all_stores = read_json(STORES_FILE)
    selected = [s for s in all_stores if s.get("id") in store_ids and s.get("status") == "Unassigned"]
    if not selected:
        return None, [], None

    hub_name = selected[0].get("hub") if selected[0].get("hub") in HUBS else "San Antonio"

    if mode == "selection":
        order = {sid: i for i, sid in enumerate(store_ids)}
        ordered = sorted(selected, key=lambda s: order.get(s.get("id"), 999))
    else:
        ordered = order_nearest_from_hub(hub_name, selected)

    metrics = calculate_route_metrics(ordered, hub_name)
    return hub_name, ordered, metrics

def coords_for(city, state):
    city = clean(city)
    return CITY_COORDS.get(city, (30.2672, -97.7431))

def assign_hub(lat, lng, dispatch_group=""):
    group = clean(dispatch_group).lower()
    if "houston" in group: return "Houston", "Dispatch Group"
    if "san antonio" in group or group == "sa" or "susatxus" in group: return "San Antonio", "Dispatch Group"
    if "dallas" in group or "irving" in group: return "Dallas", "Dispatch Group"

    nearest, nearest_miles = None, 999999
    for hub_name, hub in HUBS.items():
        miles = miles_between(lat, lng, hub["lat"], hub["lng"])
        if miles < nearest_miles:
            nearest, nearest_miles = hub_name, miles

    if nearest_miles <= 100:
        return nearest, f"Nearest Hub {round(nearest_miles, 1)} mi"
    return "Manual Review", f"Outside 100 mi ({round(nearest_miles, 1)} mi)"

def extract_pdf_text(path):
    reader = PdfReader(str(path))
    text = []
    for page in reader.pages:
        try:
            text.append(page.extract_text() or "")
        except Exception:
            pass
    return "\n".join(text)

def find_match(pattern, text, default=""):
    m = re.search(pattern, text, re.I | re.S)
    return clean(m.group(1)) if m else default

def parse_city_state_zip(value):
    value = clean(value).replace("\n", " ")
    m = re.search(r"(.+?),\s*([A-Za-z]+)\s+(\d{5})", value)
    if not m:
        m = re.search(r"(.+?)\s+(Texas|TX)\s+(\d{5})", value, re.I)
    if m:
        city = clean(m.group(1))
        state = "TX" if m.group(2).lower() in ["texas", "tx"] else clean(m.group(2))
        zip_code = clean(m.group(3))
        return city, state, zip_code
    return value, "TX", ""

def parse_rms_pdf(path):
    text = extract_pdf_text(path)

    bol = find_match(r"Bill of Lading:\s*([0-9]+)", text)
    origin = find_match(r"Origin:\s*([A-Z0-9_-]+)", text)
    store_name = find_match(r"Origin:\s*[A-Z0-9_-]+\s*Name:\s*([^\n]+)", text) or find_match(r"Name:\s*([^\n]+)", text)
    address = find_match(r"Origin:.*?Address:\s*([^\n]+)", text)
    city_state_zip = find_match(r"Origin:.*?City/State/Zip:\s*([^\n]+)", text)
    destination = find_match(r"Destination:\s*([A-Z0-9_-]+)", text)
    city, state, zip_code = parse_city_state_zip(city_state_zip)

    corner_posts = num(find_match(r'84"\s*Corner Post Only\s+R-CPH84\s+\d+\s+[\d,]+\s+([\d,]+)', text))
    drb40 = num(find_match(r'40"\s*DRB\s+R-DRB40\s+\d+\s+[\d,]+\s+([\d,]+)', text))
    drb48 = num(find_match(r'48"\s*DRB\s+R-DRB48\s+\d+\s+[\d,]+\s+([\d,]+)', text))
    wood_shelf = num(find_match(r'Wood Shelf\s+R-W4048\s+\d+\s+[\d,]+\s+([\d,]+)', text))
    bol_weight = num(find_match(r"Bill of Lading Total Weight:\s*([\d,]+)", text) or find_match(r"Order Total Weight:\s*([\d,]+)", text))

    expected_racks = round(corner_posts / 4, 2) if corner_posts else 0
    lat, lng = coords_for(city, state)
    hub, hub_reason = assign_hub(lat, lng, destination)

    review_reasons = []
    if not bol: review_reasons.append("Missing BOL")
    if not origin: review_reasons.append("Missing origin/store number")
    if not city: review_reasons.append("Missing city")
    if expected_racks <= 0: review_reasons.append('Missing 84" Corner Post quantity')
    if hub == "Manual Review": review_reasons.append("Hub outside 100 miles")

    status = "Need Review" if review_reasons else "Unassigned"

    return {
        "id": str(uuid4()),
        "bol": bol,
        "origin": origin,
        "store_name": store_name,
        "address": address,
        "city": city,
        "state": state,
        "zip": zip_code,
        "lat": lat,
        "lng": lng,
        "hub": hub,
        "hub_reason": hub_reason,
        "dispatch_group": destination,
        "expected_racks": expected_racks,
        "corner_posts": corner_posts,
        "drb40": drb40,
        "drb48": drb48,
        "wood_shelf": wood_shelf,
        "weight": bol_weight or round(expected_racks * DEFAULT_RACK_WEIGHT, 2),
        "status": status,
        "review_reasons": review_reasons,
        "assigned_driver": "",
        "pdf_path": "",
        "created_at": datetime.now().isoformat(timespec="seconds")
    }

def normalize_row(row):
    bol = clean(row.get("BOL #") or row.get("BOL") or row.get("BOL Number"))
    origin = clean(row.get("Origin") or row.get("Store") or row.get("Store Name"))
    store_name = clean(row.get("Store Name")) or origin or f"BOL {bol}"
    city = clean(row.get("City") or row.get("Origin City"))
    state = clean(row.get("State") or row.get("Origin State")) or "TX"
    address = clean(row.get("Origin Address") or row.get("Carrier Address") or row.get("Address"))
    dispatch_group = clean(row.get("Dispatch Group") or row.get("Route"))
    racks = num(row.get("Est Racks") or row.get("Expected Racks") or row.get("Racks"))

    lat, lng = coords_for(city, state)
    hub, hub_reason = assign_hub(lat, lng, dispatch_group)
    return {"id": str(uuid4()), "bol": bol, "origin": origin, "store_name": store_name, "address": address, "city": city, "state": state, "lat": lat, "lng": lng, "hub": hub, "hub_reason": hub_reason, "dispatch_group": dispatch_group, "expected_racks": racks, "weight": round(racks * DEFAULT_RACK_WEIGHT, 2), "status": "Unassigned", "assigned_driver": "", "pdf_path": "", "created_at": datetime.now().isoformat(timespec="seconds")}

def parse_xlsx(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    sheet_name = "BOL_Intake" if "BOL_Intake" in wb.sheetnames else wb.sheetnames[0]
    ws = wb[sheet_name]
    headers = [clean(ws.cell(1, c).value) for c in range(1, ws.max_column + 1)]
    rows = []
    for r in range(2, ws.max_row + 1):
        raw, has_data = {}, False
        for c, header in enumerate(headers, start=1):
            value = ws.cell(r, c).value
            if value not in [None, ""]: has_data = True
            raw[header] = value
        if has_data: rows.append(normalize_row(raw))
    return rows

def parse_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
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
    return render_template("dispatch_map.html", stores=stores, hubs=HUBS, max_payload=MAX_PAYLOAD)

@app.route("/route-builder")
def route_builder():
    routes = read_json(ROUTES_FILE)
    return render_template("route_builder.html", routes=routes)

@app.route("/rms-import", methods=["GET", "POST"])
def rms_import():
    if request.method == "POST":
        files = request.files.getlist("rms_file")
        if not files or files[0].filename == "":
            return render_template("rms_import.html", message="Choose RMS PDF, Excel, or CSV files first.")

        existing = read_json(STORES_FILE)
        existing_keys = {(s.get("bol"), s.get("origin")) for s in existing}
        added, duplicates, review = 0, 0, 0

        for uploaded in files:
            filename = secure_filename(uploaded.filename)
            temp_path = UPLOAD_DIR / filename
            uploaded.save(temp_path)

            imported = []
            if filename.lower().endswith(".pdf"):
                item = parse_rms_pdf(temp_path)
                clean_name = f"BOL_{safe_part(item.get('bol'))}_{safe_part(item.get('origin'))}_{safe_part(item.get('store_name'))}_{safe_part(item.get('city'))}_{safe_part(item.get('state'))}.pdf"
                root = "Need_Review" if item["status"] == "Need Review" else "Imported"
                final_path = month_folder(root) / clean_name
                shutil.move(str(temp_path), str(final_path))
                item["pdf_path"] = str(final_path)
                imported = [item]
            elif filename.lower().endswith(".xlsx"):
                imported = parse_xlsx(temp_path)
            elif filename.lower().endswith(".csv"):
                imported = parse_csv(temp_path)
            else:
                continue

            for item in imported:
                key = (item.get("bol"), item.get("origin"))
                if key in existing_keys and any(key):
                    duplicates += 1
                    continue
                existing.append(item)
                existing_keys.add(key)
                added += 1
                if item.get("status") == "Need Review":
                    review += 1

        write_json(STORES_FILE, existing)
        audit("RMS Import", {"added": added, "duplicates": duplicates, "need_review": review})
        return render_template("rms_import.html", message=f"Import complete. Added {added}. Need Review {review}. Skipped duplicates {duplicates}.")

    return render_template("rms_import.html", message="")

@app.route("/need-review")
def need_review():
    stores = [s for s in read_json(STORES_FILE) if s.get("status") == "Need Review"]
    return render_template("need_review.html", stores=stores, hubs=HUBS)

@app.route("/api/approve-review", methods=["POST"])
def api_approve_review():
    data = request.get_json(force=True)
    store_id = data.get("store_id")
    hub = data.get("hub")
    stores = read_json(STORES_FILE)
    updated = None
    for store in stores:
        if store["id"] == store_id:
            store["hub"] = hub or store.get("hub")
            store["status"] = "Unassigned"
            store["review_reasons"] = []
            if store.get("pdf_path"):
                store["pdf_path"] = move_pdf(store["pdf_path"], "Imported")
            updated = store
            break
    write_json(STORES_FILE, stores)
    audit("Approve Need Review", {"store_id": store_id, "hub": hub})
    return jsonify({"ok": True, "store": updated})


@app.route("/rms-sync")
def rms_sync():
    settings_data = read_json(SETTINGS_FILE)
    history = read_json(SYNC_HISTORY_FILE)
    return render_template("rms_sync.html", settings=settings_data, history=history)

@app.route("/api/rms/test-connection", methods=["POST"])
def api_rms_test_connection():
    settings_data = read_json(SETTINGS_FILE)
    history = read_json(SYNC_HISTORY_FILE)

    result = {
        "id": str(uuid4()),
        "time": datetime.now().isoformat(timespec="seconds"),
        "action": "Test RMS Connection",
        "status": "READY",
        "message": "RMS sync foundation is installed. Full browser login automation is the next step after Playwright setup.",
        "login_url": settings_data.get("rms_login_url", "https://rms.reusability.com/login"),
        "bol_url": settings_data.get("rms_bol_url", "https://rms.reusability.com/bills-of-lading")
    }

    history.append(result)
    write_json(SYNC_HISTORY_FILE, history)
    audit("RMS Test Connection", result)

    return jsonify({"ok": True, "result": result})

@app.route("/api/rms/sync-open-bols", methods=["POST"])
def api_rms_sync_open_bols():
    settings_data = read_json(SETTINGS_FILE)
    history = read_json(SYNC_HISTORY_FILE)

    result = {
        "id": str(uuid4()),
        "time": datetime.now().isoformat(timespec="seconds"),
        "action": "Sync Open BOLs",
        "status": "FOUNDATION ONLY",
        "imported": 0,
        "skipped": 0,
        "need_review": 0,
        "message": "Sync dashboard is ready. Next package will add Playwright browser automation to log in, open BOLs, read printable BOL pages, and import them."
    }

    history.append(result)
    write_json(SYNC_HISTORY_FILE, history)
    audit("RMS Sync Foundation", result)

    return jsonify({"ok": True, "result": result})

@app.route("/settings", methods=["GET", "POST"])
def settings():
    settings_data = read_json(SETTINGS_FILE)
    message = ""
    if request.method == "POST":
        settings_data["rms_username"] = clean(request.form.get("rms_username"))
        settings_data["rms_login_url"] = clean(request.form.get("rms_login_url")) or "https://rms.reusability.com/login"
        settings_data["rms_bol_url"] = clean(request.form.get("rms_bol_url")) or "https://rms.reusability.com/bills-of-lading"
        settings_data["rms_password_saved"] = bool(request.form.get("rms_password"))
        write_json(SETTINGS_FILE, settings_data)
        audit("Update RMS Settings", {"username": settings_data["rms_username"], "password_saved": settings_data["rms_password_saved"]})
        message = "RMS settings saved. Automatic sync will be added later."
    return render_template("settings.html", settings=settings_data, message=message)

@app.route("/api/preview-route", methods=["POST"])
def api_preview_route():
    data = request.get_json(force=True)
    store_ids = data.get("store_ids", [])
    mode = data.get("mode", "optimized")

    hub_name, ordered, metrics = build_route_order(store_ids, mode)

    if not ordered:
        return jsonify({"ok": False, "message": "No unassigned stores selected."})

    return jsonify({
        "ok": True,
        "hub": hub_name,
        "mode": mode,
        "stores": ordered,
        "metrics": metrics
    })

@app.route("/api/assign-route", methods=["POST"])
def api_assign_route():
    data = request.get_json(force=True)
    driver = clean(data.get("driver"))
    store_ids = data.get("store_ids", [])
    mode = data.get("mode", "optimized")

    hub_name, ordered, metrics = build_route_order(store_ids, mode)

    if not ordered:
        return jsonify({"ok": False, "message": "No unassigned stores selected."})

    if metrics["status"] == "OVER LIMIT":
        return jsonify({"ok": False, "message": "Route is over 25,001 lbs. Remove stores before assigning."})

    stores = read_json(STORES_FILE)
    assigned_ids = [s["id"] for s in ordered]

    for store in stores:
        if store["id"] in assigned_ids:
            store["status"] = "Assigned"
            store["assigned_driver"] = driver
            if store.get("pdf_path"):
                store["pdf_path"] = move_pdf(store["pdf_path"], "Assigned")

    routes = read_json(ROUTES_FILE)
    route_number = f"RT-{len(routes) + 1:05d}"

    route = {
        "id": str(uuid4()),
        "route_number": route_number,
        "driver": driver,
        "hub": hub_name,
        "mode": mode,
        "store_ids": assigned_ids,
        "stops": ordered,
        "metrics": metrics,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "Assigned"
    }

    routes.append(route)
    write_json(STORES_FILE, stores)
    write_json(ROUTES_FILE, routes)
    audit("Assign Route", {"route_number": route_number, "driver": driver, "stores": len(ordered), "mode": mode})

    return jsonify({"ok": True, "route": route, "assigned": ordered, "metrics": metrics})

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
            if store.get("pdf_path"):
                store["pdf_path"] = move_pdf(store["pdf_path"], "Imported")
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
            if store.get("pdf_path"):
                store["pdf_path"] = move_pdf(store["pdf_path"], "Completed")
            updated = store
            break
    write_json(STORES_FILE, stores)
    audit("Driver Complete", {"store_id": store_id, "collected_racks": collected_racks})
    return jsonify({"ok": True, "store": updated})

if __name__ == "__main__":
    ensure_dirs()
    app.run(debug=True)
