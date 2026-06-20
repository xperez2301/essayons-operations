import os
import csv
import json
import math
import re
import shutil
import requests
import secrets
from functools import wraps
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import Flask, jsonify, render_template, request, send_file, abort, redirect, url_for, session
from openpyxl import load_workbook
from pypdf import PdfReader
from werkzeug.utils import secure_filename
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

app = Flask(__name__)

# EOMS Authentication
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE_ME_SET_SECRET_KEY_IN_AZURE")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ChangeMeNow123!")
SESSION_TIMEOUT_MINUTES = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "720"))


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
BOL_DIR = BASE_DIR / "bol_files"

STORES_FILE = DATA_DIR / "stores.json"
ROUTES_FILE = DATA_DIR / "routes.json"
AUDIT_FILE = DATA_DIR / "audit_log.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
SYNC_HISTORY_FILE = DATA_DIR / "sync_history.json"
RMS_QUEUE_FILE = DATA_DIR / "rms_queue.json"

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
        (SETTINGS_FILE, {"rms_username": "", "rms_password": "", "rms_password_saved": False, "remember_rms_credentials": True, "last_rms_login": "", "rms_connection_status": "Not Tested", "rms_login_url": "https://rms.reusability.com/login", "rms_bol_url": "https://rms.reusability.com/bills-of-lading", "google_maps_api_key": "", "telnyx_api_key": "", "telnyx_from_number": "+12103529669", "public_eoms_url": ""}),
        (SYNC_HISTORY_FILE, []),
        (RMS_QUEUE_FILE, [])
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


def full_address_for_item(address, city, state, zip_code):
    parts = [clean(address), clean(city), clean(state), clean(zip_code)]
    return ", ".join([p for p in parts if p])

def geocode_address_google(address):
    settings_data = read_json(SETTINGS_FILE)
    api_key = clean(settings_data.get("google_maps_api_key"))
    address = clean(address)

    if not api_key or not address:
        return None, None, "No Google API key or address"

    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": api_key},
            timeout=12
        )
        data = response.json()
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"], data["results"][0].get("formatted_address", address)
        return None, None, f"Geocode failed: {data.get('status')}"
    except Exception as e:
        return None, None, f"Geocode error: {str(e)[:120]}"

def resolve_store_coordinates(address, city, state, zip_code):
    full_address = full_address_for_item(address, city, state, zip_code)
    lat, lng, note = geocode_address_google(full_address)

    if lat and lng:
        return lat, lng, f"Google geocoded: {note}", full_address

    # Fallback only when geocoding is unavailable.
    lat, lng = coords_for(city, state)
    return lat, lng, f"City fallback: {note}", full_address

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
    assigned_date = find_match(r"Assigned Date\s*[:\s]*([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
    due_date = find_match(r"Due Date(?: \(PDT\))?\s*[:\s]*([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
    bol_weight = num(find_match(r"Bill of Lading Total Weight:\s*([\d,]+)", text) or find_match(r"Order Total Weight:\s*([\d,]+)", text))

    expected_racks = round(corner_posts / 4, 2) if corner_posts else 0
    lat, lng, geocode_status, full_address = resolve_store_coordinates(address, city, state, zip_code)
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
        "full_address": full_address,
        "geocode_status": geocode_status,
        "city": city,
        "state": state,
        "zip": zip_code,
        "lat": lat,
        "lng": lng,
        "hub": hub,
        "hub_reason": hub_reason,
        "dispatch_group": destination,
        "assigned_date": assigned_date,
        "due_date": due_date,
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

    zip_code = clean(row.get("Zip") or row.get("ZIP") or row.get("Origin Zip"))
    lat, lng, geocode_status, full_address = resolve_store_coordinates(address, city, state, zip_code)
    hub, hub_reason = assign_hub(lat, lng, dispatch_group)
    return {"id": str(uuid4()), "bol": bol, "origin": origin, "store_name": store_name, "address": address, "full_address": full_address, "geocode_status": geocode_status, "city": city, "state": state, "zip": zip_code, "lat": lat, "lng": lng, "hub": hub, "hub_reason": hub_reason, "dispatch_group": dispatch_group, "expected_racks": racks, "weight": round(racks * DEFAULT_RACK_WEIGHT, 2), "status": "Unassigned", "assigned_driver": "", "pdf_path": "", "created_at": datetime.now().isoformat(timespec="seconds")}

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



@app.route("/api/dispatch-board-live")
def api_dispatch_board_live():
    stores = read_json(STORES_FILE)
    routes = read_json(ROUTES_FILE)

    counts = {
        "Need Review": 0,
        "Unassigned": 0,
        "Assigned": 0,
        "Dispatched": 0,
        "Completed": 0
    }

    for s in stores:
        status = clean(s.get("status")) or "Unassigned"
        if status not in counts:
            status = "Unassigned"
        counts[status] += 1

    active = [s for s in stores if (clean(s.get("status")) or "Unassigned") in ["Need Review", "Unassigned", "Assigned", "Dispatched"]]
    racks = sum(num(s.get("expected_racks")) for s in active)
    weight = sum(num(s.get("weight")) for s in active)
    pieces = racks * PIECES_PER_RACK

    return jsonify({
        "ok": True,
        "stores": stores,
        "routes": routes,
        "counts": counts,
        "metrics": {
            "racks": round(racks, 2),
            "weight": round(weight, 2),
            "revenue": round(pieces * RATE_PER_PIECE, 2),
            "driver_pay": round(pieces * DRIVER_PAY_PER_PIECE, 2)
        }
    })

@app.route("/api/dispatch-map-debug")
def api_dispatch_map_debug():
    stores = read_json(STORES_FILE)
    return jsonify({
        "total_stores": len(stores),
        "unassigned": len([s for s in stores if s.get("status") == "Unassigned"]),
        "need_review": len([s for s in stores if s.get("status") == "Need Review"]),
        "assigned": len([s for s in stores if s.get("status") == "Assigned"]),
        "completed": len([s for s in stores if s.get("status") == "Completed"]),
        "map_eligible": [
            {
                "bol": s.get("bol"),
                "status": s.get("status"),
                "lat": s.get("lat"),
                "lng": s.get("lng"),
                "city": s.get("city"),
                "store_name": s.get("store_name"),
                "racks": s.get("expected_racks"),
                "address": s.get("address"),
                "full_address": s.get("full_address"),
                "geocode_status": s.get("geocode_status")
            }
            for s in stores if s.get("status") == "Unassigned"
        ]
    })


@app.route("/api/geocode-stores", methods=["POST"])
def api_geocode_stores():
    stores = read_json(STORES_FILE)
    updated = 0
    failed = 0

    for store in stores:
        address = store.get("address") or store.get("origin_address") or ""
        city = store.get("city") or store.get("origin_city") or ""
        state = store.get("state") or store.get("origin_state") or "TX"
        zip_code = store.get("zip") or store.get("origin_zip") or ""

        if not address or not city:
            failed += 1
            store["geocode_status"] = "Missing address or city"
            continue

        lat, lng, geocode_status, full_address = resolve_store_coordinates(address, city, state, zip_code)
        store["lat"] = lat
        store["lng"] = lng
        store["full_address"] = full_address
        store["geocode_status"] = geocode_status

        if "Google geocoded" in geocode_status:
            updated += 1
        else:
            failed += 1

    write_json(STORES_FILE, stores)
    audit("Geocode Stores", {"updated": updated, "failed": failed})

    return jsonify({"ok": True, "updated": updated, "failed": failed})

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
        if store.get("id") == store_id:
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



def rms_login_with_playwright(headless=False):
    settings_data = read_json(SETTINGS_FILE)

    username = clean(settings_data.get("rms_username"))
    password = clean(settings_data.get("rms_password"))
    login_url = settings_data.get("rms_login_url") or "https://rms.reusability.com/login"
    bol_url = settings_data.get("rms_bol_url") or "https://rms.reusability.com/bills-of-lading"

    if not username or not password:
        return {
            "ok": False,
            "status": "MISSING CREDENTIALS",
            "message": "Save RMS username and password in Settings first.",
            "bol_count": 0,
            "sample_bols": []
        }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=60000)

            # RMS login fields from observed page
            page.locator('input[name="username"], input[type="email"], input[placeholder*="Username"], input').first.fill(username)

            password_box = page.locator('input[type="password"]').first
            password_box.fill(password)

            page.get_by_role("button", name=re.compile("Sign In|Login", re.I)).click()

            page.wait_for_load_state("networkidle", timeout=60000)

            page.goto(bol_url, wait_until="networkidle", timeout=60000)

            # Detect BOL links across all pages
            bol_links = collect_bol_links_from_all_pages(page)

            # Save diagnostic screenshot for troubleshooting
            diag_dir = BASE_DIR / "diagnostics"
            diag_dir.mkdir(exist_ok=True)
            screenshot_path = diag_dir / f"rms_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            page.screenshot(path=str(screenshot_path), full_page=True)

            browser.close()

            return {
                "ok": True,
                "status": "LOGIN SUCCESS",
                "message": f"RMS login successful. Found {len(bol_links)} BOL links on the Bills of Lading page.",
                "bol_count": len(bol_links),
                "sample_bols": bol_links[:10],
                "screenshot": str(screenshot_path)
            }

        except PlaywrightTimeoutError as e:
            browser.close()
            return {
                "ok": False,
                "status": "TIMEOUT",
                "message": f"RMS page timed out: {str(e)[:200]}",
                "bol_count": 0,
                "sample_bols": []
            }
        except Exception as e:
            browser.close()
            return {
                "ok": False,
                "status": "ERROR",
                "message": f"RMS login automation error: {str(e)[:300]}",
                "bol_count": 0,
                "sample_bols": []
            }




def extract_printable_bol_from_text(text, source_url=""):
    raw = text or ""
    lines = [clean(x) for x in raw.splitlines() if clean(x)]
    joined = "\n".join(lines)

    bol = find_match(r"Bill of Lading[:\s#-]*([0-9]+)", joined)
    if not bol:
        bol = find_match(r"Bill of Lading\s*-\s*([0-9]+)", joined)
    if not bol:
        bol = find_match(r"/bills-of-lading/([0-9]+)/print", source_url)

    origin = find_match(r"Origin[:\s]+([A-Z0-9_-]+)", joined)
    destination = find_match(r"Destination[:\s]+([A-Z0-9_-]+)", joined)

    def capture_section(start_label, stop_labels):
        start_idx = None
        for i, line in enumerate(lines):
            if re.search(rf"^{re.escape(start_label)}", line, re.I):
                start_idx = i
                break
        if start_idx is None:
            return ""

        captured = []
        for line in lines[start_idx:start_idx + 18]:
            if captured and any(re.search(rf"^{re.escape(stop)}", line, re.I) for stop in stop_labels):
                break
            captured.append(line)
        return "\n".join(captured)

    origin_section = capture_section("Origin", ["Destination", "Carrier", "Bill of Lading", "Arrival Time"])
    destination_section = capture_section("Destination", ["Carrier", "Bill of Lading", "Arrival Time"])

    def field_from(section, label):
        m = re.search(rf"{label}:\s*([^\n]+)", section, re.I)
        return clean(m.group(1)) if m else ""

    origin_name = field_from(origin_section, "Name")
    origin_address = field_from(origin_section, "Address")
    origin_city_line = field_from(origin_section, "City/State/Zip")
    origin_contact = field_from(origin_section, "Contact")

    dest_name = field_from(destination_section, "Name")
    dest_address = field_from(destination_section, "Address")
    dest_city_line = field_from(destination_section, "City/State/Zip")
    dest_contact = field_from(destination_section, "Contact")

    city, state, zip_code = parse_city_state_zip(origin_city_line)
    if not city:
        city, state, zip_code = parse_city_state_zip(dest_city_line)

    # Store fields use origin/pickup side.
    store_name = origin_name
    address = origin_address
    contact = origin_contact

    # Fallbacks from any visible label.
    if not store_name:
        store_name = find_match(r"Name:\s*([^\n]+)", joined)
    if not address:
        address = find_match(r"Address:\s*([^\n]+)", joined)
    if not city:
        tx_line = ""
        for line in lines:
            if re.search(r",?\s*TX\s+\d{5}|Texas\s+\d{5}", line, re.I):
                tx_line = line
                break
        if tx_line:
            city, state, zip_code = parse_city_state_zip(tx_line)

    def item_qty(label):
        patterns = [
            rf'{re.escape(label)}\s+R-[A-Z0-9]+\s+[\d,]+\s+[\d,]+\s+([\d,]+)',
            rf'{re.escape(label)}.*?R-[A-Z0-9]+.*?(\d+)\s*$',
            rf'{re.escape(label)}.*?Qty[:\s]+([\d,]+)'
        ]
        for pat in patterns:
            m = re.search(pat, joined, re.I | re.M)
            if m:
                return num(m.group(1))

        # Table fallback: find the item line and use the last number on the same row.
        for line in lines:
            if label.lower() in line.lower():
                nums = re.findall(r"\d+", line.replace(",", ""))
                if nums:
                    return num(nums[-1])
        return 0

    corner_posts = item_qty('84" Corner Post Only')
    drb40 = item_qty('40" DRB')
    drb48 = item_qty('48" DRB')
    wood_shelf = item_qty('Wood Shelf')


    assigned_date = find_match(r"Assigned Date\s*[:\s]*([0-9]{2}/[0-9]{2}/[0-9]{4})", joined)
    due_date = find_match(r"Due Date(?: \(PDT\))?\s*[:\s]*([0-9]{2}/[0-9]{2}/[0-9]{4})", joined)

    bol_weight = num(
        find_match(r"Bill of Lading Total Weight:\s*([\d,]+)", joined)
        or find_match(r"Order Total Weight:\s*([\d,]+)", joined)
    )

    expected_racks = round(corner_posts / 4, 2) if corner_posts else 0
    lat, lng, geocode_status, full_address = resolve_store_coordinates(address, city, state, zip_code)
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
        "full_address": full_address,
        "geocode_status": geocode_status,
        "city": city,
        "state": state,
        "zip": zip_code,
        "contact": contact,
        "origin_name": origin_name,
        "origin_address": origin_address,
        "origin_city": city,
        "origin_state": state,
        "origin_zip": zip_code,
        "origin_contact": origin_contact,
        "destination": destination,
        "destination_name": dest_name,
        "destination_address": dest_address,
        "destination_city_state_zip": dest_city_line,
        "destination_contact": dest_contact,
        "lat": lat,
        "lng": lng,
        "hub": hub,
        "hub_reason": hub_reason,
        "dispatch_group": destination,
        "assigned_date": assigned_date,
        "due_date": due_date,
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
        "rms_url": source_url,
        "created_at": datetime.now().isoformat(timespec="seconds")
    }

def save_printable_snapshot(item, html):
    root = "Need_Review" if item.get("status") == "Need Review" else "Imported"
    filename = f"BOL_{safe_part(item.get('bol'))}_{safe_part(item.get('origin'))}_{safe_part(item.get('store_name'))}_{safe_part(item.get('city'))}_{safe_part(item.get('state'))}.html"
    final_path = month_folder(root) / filename
    final_path.write_text(html, encoding="utf-8", errors="ignore")
    return str(final_path)


def extract_date_from_text(text):
    text = clean(text)
    patterns = [
        r"\b(\d{1,2}/\d{1,2}/\d{4})\b",
        r"\b(\d{4}-\d{2}-\d{2})\b"
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return clean(m.group(1))
    return ""

def normalize_due_date(value):
    value = clean(value)
    if not value:
        return ""
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return datetime.strptime(value, "%Y-%m-%d").strftime("%m/%d/%Y")
        if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", value):
            return datetime.strptime(value, "%m/%d/%Y").strftime("%m/%d/%Y")
    except Exception:
        pass
    return value

def collect_bol_links_from_all_pages(page, max_pages=50):
    bol_links = []
    seen = set()

    def harvest_current_page():
        anchors = page.locator("a").all()
        found = []
        for a in anchors:
            try:
                text = clean(a.inner_text())
                href = a.get_attribute("href") or ""
                if re.fullmatch(r"\d{4,}", text) and text not in seen:
                    seen.add(text)

                    row_text = ""
                    due_date = ""
                    assigned_date = ""

                    try:
                        row = a.locator("xpath=ancestor::tr[1]")
                        if row.count():
                            row_text = clean(row.first.inner_text())
                    except Exception:
                        row_text = ""

                    # RMS list row usually contains assigned/due dates. Capture first/last date as fallback.
                    dates = re.findall(r"\b\d{1,2}/\d{1,2}/\d{4}\b|\b\d{4}-\d{2}-\d{2}\b", row_text)
                    if dates:
                        assigned_date = normalize_due_date(dates[0])
                        due_date = normalize_due_date(dates[-1])

                    # If row labels exist, prefer labeled due date.
                    labeled_due = find_match(r"Due Date(?:\s*\(PDT\))?\s*[:\s]*([0-9/\-]+)", row_text)
                    if labeled_due:
                        due_date = normalize_due_date(labeled_due)

                    found.append({
                        "bol": text,
                        "href": href,
                        "row_text": row_text,
                        "assigned_date": assigned_date,
                        "due_date": due_date
                    })
            except Exception:
                pass
        return found

    # Try setting rows per page to largest available value first.
    try:
        selects = page.locator("select").all()
        for sel in selects:
            try:
                options_text = sel.inner_text()
                if "20" in options_text and ("50" in options_text or "100" in options_text):
                    if "100" in options_text:
                        sel.select_option(label="100")
                    elif "50" in options_text:
                        sel.select_option(label="50")
                    page.wait_for_timeout(1500)
                    break
            except Exception:
                pass
    except Exception:
        pass

    for page_index in range(max_pages):
        page.wait_for_timeout(800)
        bol_links.extend(harvest_current_page())

        # Find and click next page arrow. RMS uses pagination with numeric pages and arrows.
        clicked = False

        # First try button/link with text that looks like next arrow.
        possible_next = [
            'button:has-text("›")',
            'button:has-text(">")',
            'a:has-text("›")',
            'a:has-text(">")',
            'button[aria-label*="Next"]',
            'a[aria-label*="Next"]'
        ]

        for selector in possible_next:
            try:
                loc = page.locator(selector).last
                if loc.count() and loc.is_enabled():
                    before = len(bol_links)
                    loc.click()
                    page.wait_for_timeout(1800)
                    clicked = True
                    break
            except Exception:
                pass

        if clicked:
            continue

        # Fallback: click next numeric page if visible.
        try:
            next_number = str(page_index + 2)
            loc = page.get_by_text(next_number, exact=True)
            if loc.count() and loc.first.is_visible():
                loc.first.click()
                page.wait_for_timeout(1800)
                clicked = True
        except Exception:
            pass

        if not clicked:
            break

    # De-dupe just in case.
    unique = []
    seen2 = set()
    for item in bol_links:
        if item["bol"] not in seen2:
            unique.append(item)
            seen2.add(item["bol"])
    return unique

def open_printable_and_extract(page, bol_link):
    bol = bol_link.get("bol")
    href = bol_link.get("href") or ""

    # Navigate to BOL detail.
    if href.startswith("http"):
        page.goto(href, wait_until="networkidle", timeout=60000)
    elif href.startswith("/"):
        page.goto("https://rms.reusability.com" + href, wait_until="networkidle", timeout=60000)
    else:
        # Fallback click by BOL text from list page if relative URL missing.
        page.get_by_text(bol, exact=True).click()
        page.wait_for_load_state("networkidle", timeout=60000)

    # Click printable BOL link.
    printable_clicked = False
    try:
        page.get_by_text(re.compile("View Printable Bill of Lading|Print this Bill of Lading", re.I)).first.click()
        page.wait_for_load_state("networkidle", timeout=60000)
        printable_clicked = True
    except Exception:
        pass

    if not printable_clicked:
        try:
            page.locator('a:has-text("Printable")').first.click()
            page.wait_for_load_state("networkidle", timeout=60000)
            printable_clicked = True
        except Exception:
            pass

    text = page.locator("body").inner_text(timeout=60000)
    html = page.content()
    item = extract_printable_bol_from_text(text, page.url)
    if not item.get("bol"):
        item["bol"] = bol
        item["review_reasons"].append("BOL fallback from list")
        item["status"] = "Need Review"
    item["pdf_path"] = save_printable_snapshot(item, html)
    return item


def scan_rms_queue_with_playwright(headless=False):
    settings_data = read_json(SETTINGS_FILE)

    username = clean(settings_data.get("rms_username"))
    password = clean(settings_data.get("rms_password"))
    login_url = settings_data.get("rms_login_url") or "https://rms.reusability.com/login"
    bol_url = settings_data.get("rms_bol_url") or "https://rms.reusability.com/bills-of-lading"

    if not username or not password:
        return {
            "ok": False,
            "status": "MISSING CREDENTIALS",
            "message": "Save RMS username and password in Settings first.",
            "found": 0,
            "new": 0,
            "existing": 0
        }

    existing_stores = read_json(STORES_FILE)
    existing_bols = {clean(s.get("bol")) for s in existing_stores if clean(s.get("bol"))}
    current_queue = read_json(RMS_QUEUE_FILE)
    queue_by_bol = {clean(q.get("bol")): q for q in current_queue if clean(q.get("bol"))}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()

        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            page.locator('input[name="username"], input[type="email"], input[placeholder*="Username"], input').first.fill(username)
            page.locator('input[type="password"]').first.fill(password)
            page.get_by_role("button", name=re.compile("Sign In|Login", re.I)).click()
            page.wait_for_load_state("networkidle", timeout=60000)

            page.goto(bol_url, wait_until="networkidle", timeout=60000)
            bol_links = collect_bol_links_from_all_pages(page)

            new_count = 0
            existing_count = 0

            for item in bol_links:
                bol = clean(item.get("bol"))
                if not bol:
                    continue

                status = "Imported" if bol in existing_bols else "New"
                if bol in existing_bols:
                    existing_count += 1
                else:
                    new_count += 1

                if bol in queue_by_bol:
                    # preserve ignored/manual status unless already imported
                    old = queue_by_bol[bol]
                    if old.get("queue_status") in ["Ignored", "Need Review"] and status != "Imported":
                        status = old.get("queue_status")
                    old.update({
                        "href": item.get("href", ""),
                        "queue_status": status,
                        "due_date": item.get("due_date", old.get("due_date", "")),
                        "assigned_date": item.get("assigned_date", old.get("assigned_date", "")),
                        "row_text": item.get("row_text", old.get("row_text", "")),
                        "last_seen": datetime.now().isoformat(timespec="seconds")
                    })
                else:
                    queue_by_bol[bol] = {
                        "id": str(uuid4()),
                        "bol": bol,
                        "href": item.get("href", ""),
                        "queue_status": status,
                        "store_name": "",
                        "origin": "",
                        "city": "",
                        "state": "",
                        "hub": "",
                        "expected_racks": "",
                        "weight": "",
                        "due_date": item.get("due_date", ""),
                        "assigned_date": item.get("assigned_date", ""),
                        "row_text": item.get("row_text", ""),
                        "last_seen": datetime.now().isoformat(timespec="seconds"),
                        "created_at": datetime.now().isoformat(timespec="seconds")
                    }

            queue = list(queue_by_bol.values())
            queue.sort(key=lambda x: x.get("bol", ""), reverse=True)
            write_json(RMS_QUEUE_FILE, queue)

            diag_dir = BASE_DIR / "diagnostics"
            diag_dir.mkdir(exist_ok=True)
            page.screenshot(path=str(diag_dir / f"rms_queue_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"), full_page=True)

            browser.close()

            return {
                "ok": True,
                "status": "QUEUE UPDATED",
                "message": f"RMS queue updated. Found {len(bol_links)} BOLs. New {new_count}. Already imported {existing_count}.",
                "found": len(bol_links),
                "new": new_count,
                "existing": existing_count
            }

        except Exception as e:
            browser.close()
            return {
                "ok": False,
                "status": "ERROR",
                "message": f"RMS queue scan error: {str(e)[:300]}",
                "found": 0,
                "new": 0,
                "existing": 0
            }


def upsert_store_by_bol(item):
    stores = read_json(STORES_FILE)
    replaced = False
    for idx, existing in enumerate(stores):
        if clean(existing.get("bol")) == clean(item.get("bol")):
            item["id"] = existing.get("id", item.get("id"))
            stores[idx] = item
            replaced = True
            break
    if not replaced:
        stores.append(item)
    write_json(STORES_FILE, stores)
    return item

def update_queue_from_item(item):
    queue = read_json(RMS_QUEUE_FILE)
    for q in queue:
        if clean(q.get("bol")) == clean(item.get("bol")):
            q["queue_status"] = "Imported" if item.get("status") == "Unassigned" else "Need Review"
            q["store_name"] = item.get("store_name", "")
            q["origin"] = item.get("origin", "")
            q["city"] = item.get("city", "")
            q["state"] = item.get("state", "")
            q["address"] = item.get("address", "")
            q["contact"] = item.get("contact", "")
            q["origin_name"] = item.get("origin_name", "")
            q["origin_address"] = item.get("origin_address", "")
            q["origin_contact"] = item.get("origin_contact", "")
            q["hub"] = item.get("hub", "")
            q["expected_racks"] = item.get("expected_racks", "")
            q["weight"] = item.get("weight", "")
            q["due_date"] = item.get("due_date", "")
            q["assigned_date"] = item.get("assigned_date", "")
            q["pdf_path"] = item.get("pdf_path", "")
            q["geocode_status"] = item.get("geocode_status", "")
            q["full_address"] = item.get("full_address", "")
            q["imported_at"] = datetime.now().isoformat(timespec="seconds")
            break
    write_json(RMS_QUEUE_FILE, queue)

def import_selected_queue_bols(bol_numbers, headless=False):
    settings_data = read_json(SETTINGS_FILE)

    username = clean(settings_data.get("rms_username"))
    password = clean(settings_data.get("rms_password"))
    login_url = settings_data.get("rms_login_url") or "https://rms.reusability.com/login"

    if not username or not password:
        return {
            "ok": False,
            "status": "MISSING CREDENTIALS",
            "message": "Save RMS username and password in Settings first.",
            "imported": 0,
            "skipped": 0,
            "need_review": 0,
            "errors": []
        }

    queue = read_json(RMS_QUEUE_FILE)
    queue_by_bol = {clean(q.get("bol")): q for q in queue}

    imported = 0
    need_review = 0
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()

        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            page.locator('input[name="username"], input[type="email"], input[placeholder*="Username"], input').first.fill(username)
            page.locator('input[type="password"]').first.fill(password)
            page.get_by_role("button", name=re.compile("Sign In|Login", re.I)).click()
            page.wait_for_load_state("networkidle", timeout=60000)

            for bol in bol_numbers:
                bol = clean(bol)
                if not bol:
                    continue

                try:
                    direct_print_url = f"https://rms.reusability.com/bills-of-lading/{bol}/print"
                    page.goto(direct_print_url, wait_until="networkidle", timeout=60000)

                    body_text = page.locator("body").inner_text(timeout=60000)
                    html = page.content()

                    item = extract_printable_bol_from_text(body_text, page.url)

                    if not item.get("bol"):
                        item["bol"] = bol
                    if clean(item.get("bol")) != bol:
                        item["bol"] = bol

                    queue_item = queue_by_bol.get(bol, {})
                    if not item.get("due_date") and queue_item.get("due_date"):
                        item["due_date"] = queue_item.get("due_date")
                    if not item.get("assigned_date") and queue_item.get("assigned_date"):
                        item["assigned_date"] = queue_item.get("assigned_date")

                    item["pdf_path"] = save_printable_snapshot(item, html)

                    # Force automatic geocoding during every Import/Re-import.
                    # This replaces city-center fallback coordinates when a Google Maps API key is saved.
                    lat, lng, geocode_status, full_address = resolve_store_coordinates(
                        item.get("address") or item.get("origin_address") or "",
                        item.get("city") or item.get("origin_city") or "",
                        item.get("state") or item.get("origin_state") or "TX",
                        item.get("zip") or item.get("origin_zip") or ""
                    )
                    item["lat"] = lat
                    item["lng"] = lng
                    item["full_address"] = full_address
                    item["geocode_status"] = geocode_status

                    upsert_store_by_bol(item)
                    update_queue_from_item(item)

                    imported += 1
                    if item.get("status") == "Need Review":
                        need_review += 1

                except Exception as e:
                    errors.append(f"BOL {bol}: {str(e)[:180]}")
                    queue = read_json(RMS_QUEUE_FILE)
                    for q in queue:
                        if clean(q.get("bol")) == bol:
                            q["queue_status"] = "Need Review"
                            q["updated_at"] = datetime.now().isoformat(timespec="seconds")
                            break
                    write_json(RMS_QUEUE_FILE, queue)

            browser.close()

            return {
                "ok": True,
                "status": "IMPORT SELECTED COMPLETE",
                "message": f"Import/Re-import complete. Processed {imported}. Need Review {need_review}.",
                "imported": imported,
                "skipped": 0,
                "need_review": need_review,
                "errors": errors[:10]
            }

        except Exception as e:
            try:
                browser.close()
            except Exception:
                pass

            return {
                "ok": False,
                "status": "ERROR",
                "message": f"Import/Re-import selected error: {str(e)[:300]}",
                "imported": imported,
                "skipped": 0,
                "need_review": need_review,
                "errors": errors[:10]
            }

def rms_full_import_with_playwright(headless=False, max_bols=0):
    settings_data = read_json(SETTINGS_FILE)

    username = clean(settings_data.get("rms_username"))
    password = clean(settings_data.get("rms_password"))
    login_url = settings_data.get("rms_login_url") or "https://rms.reusability.com/login"
    bol_url = settings_data.get("rms_bol_url") or "https://rms.reusability.com/bills-of-lading"

    if not username or not password:
        return {
            "ok": False,
            "status": "MISSING CREDENTIALS",
            "message": "Save RMS username and password in Settings first.",
            "imported": 0,
            "skipped": 0,
            "need_review": 0,
            "bol_count": 0
        }

    existing = read_json(STORES_FILE)
    existing_keys = {(s.get("bol"), s.get("origin")) for s in existing if s.get("bol") or s.get("origin")}

    imported = 0
    skipped = 0
    need_review = 0
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            page.locator('input[name="username"], input[type="email"], input[placeholder*="Username"], input').first.fill(username)
            page.locator('input[type="password"]').first.fill(password)
            page.get_by_role("button", name=re.compile("Sign In|Login", re.I)).click()
            page.wait_for_load_state("networkidle", timeout=60000)

            page.goto(bol_url, wait_until="networkidle", timeout=60000)
            bol_links = collect_bol_links_from_all_pages(page)

            if max_bols and max_bols > 0:
                bol_links = bol_links[:max_bols]

            # Diagnostic screenshot after pagination scan.
            diag_dir = BASE_DIR / "diagnostics"
            diag_dir.mkdir(exist_ok=True)
            page.screenshot(path=str(diag_dir / f"rms_pagination_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"), full_page=True)

            for link in bol_links:
                try:
                    # Open each BOL in a fresh page to avoid losing pagination state.
                    detail_page = browser.new_page()
                    detail_page.goto(bol_url, wait_until="networkidle", timeout=60000)
                    direct_print_url = f"https://rms.reusability.com/bills-of-lading/{link['bol']}/print"
                    detail_page.goto(direct_print_url, wait_until="networkidle", timeout=60000)

                    text = detail_page.locator("body").inner_text(timeout=60000)
                    html = detail_page.content()
                    item = extract_printable_bol_from_text(text, detail_page.url)
                    if not item.get("bol"):
                        item["bol"] = link["bol"]
                        item["review_reasons"].append("BOL fallback from list")
                        item["status"] = "Need Review"

                    key = (item.get("bol"), item.get("origin"))
                    if key in existing_keys and any(key):
                        skipped += 1
                        detail_page.close()
                        continue

                    item["pdf_path"] = save_printable_snapshot(item, html)
                    existing.append(item)
                    existing_keys.add(key)
                    imported += 1
                    if item.get("status") == "Need Review":
                        need_review += 1

                    detail_page.close()

                except Exception as e:
                    errors.append(f"{link.get('bol')}: {str(e)[:120]}")

            write_json(STORES_FILE, existing)
            browser.close()

            return {
                "ok": True,
                "status": "IMPORT COMPLETE",
                "message": f"RMS import complete. Scanned {len(bol_links)} BOLs. Imported {imported}. Skipped {skipped}. Need Review {need_review}.",
                "bol_count": len(bol_links),
                "imported": imported,
                "skipped": skipped,
                "need_review": need_review,
                "errors": errors[:10]
            }

        except Exception as e:
            browser.close()
            return {
                "ok": False,
                "status": "ERROR",
                "message": f"RMS full import error: {str(e)[:300]}",
                "imported": imported,
                "skipped": skipped,
                "need_review": need_review,
                "bol_count": 0,
                "errors": errors[:10]
            }




@app.route("/bol-live/<bol_number>")
def bol_live_printable(bol_number):
    settings_data = read_json(SETTINGS_FILE)

    username = clean(settings_data.get("rms_username"))
    password = clean(settings_data.get("rms_password"))
    login_url = settings_data.get("rms_login_url") or "https://rms.reusability.com/login"

    if not username or not password:
        return render_template(
            "bol_not_found.html",
            bol=bol_number,
            path="RMS username/password missing. Save RMS credentials in Settings first."
        )

    direct_print_url = f"https://rms.reusability.com/bills-of-lading/{clean(bol_number)}/print"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        try:
            # Login first.
            page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            page.locator('input[name="username"], input[type="email"], input[placeholder*="Username"], input').first.fill(username)
            page.locator('input[type="password"]').first.fill(password)
            page.get_by_role("button", name=re.compile("Sign In|Login", re.I)).click()
            page.wait_for_load_state("networkidle", timeout=60000)

            # Go straight to the RMS printable URL.
            page.goto(direct_print_url, wait_until="networkidle", timeout=60000)

            html = page.content()

            # Save backup snapshot.
            backup_dir = month_folder("RMS_Backup")
            backup_file = backup_dir / f"DIRECT_PRINTABLE_BOL_{safe_part(bol_number)}_{datetime.now().strftime('%H%M%S')}.html"
            backup_file.write_text(html, encoding="utf-8", errors="ignore")

            browser.close()

            return html

        except Exception as e:
            try:
                browser.close()
            except Exception:
                pass

            return render_template(
                "bol_not_found.html",
                bol=bol_number,
                path=f"Direct printable RMS error: {str(e)[:300]}"
            )


@app.route("/bol-print/<store_id>")
def bol_print(store_id):
    stores = read_json(STORES_FILE)
    queue = read_json(RMS_QUEUE_FILE)

    found = None
    for s in stores:
        if s.get("id") == store_id or clean(s.get("bol")) == store_id:
            found = s
            break

    if not found:
        for q in queue:
            if q.get("id") == store_id or clean(q.get("bol")) == store_id:
                found = q
                break

    if not found:
        abort(404)

    path = found.get("pdf_path") or found.get("printable_path") or ""
    if not path:
        bol = safe_part(found.get("bol"))
        matches = list(BOL_DIR.rglob(f"*{bol}*.html")) + list(BOL_DIR.rglob(f"*{bol}*.pdf"))
        if matches:
            path = str(matches[0])

    if not path or not Path(path).exists():
        return render_template("bol_not_found.html", bol=found.get("bol", ""), path=path)

    content = Path(path).read_text(encoding="utf-8", errors="ignore") if str(path).lower().endswith(".html") else ""
    if content:
        return f"""<!doctype html>
<html>
<head>
<title>Print BOL {found.get('bol','')}</title>
<style>
@media print {{
  button {{ display:none!important; }}
  body {{ margin:0.25in; }}
}}
.print-toolbar {{
  position: sticky;
  top: 0;
  background: #0f172a;
  color: white;
  padding: 10px;
  display: flex;
  gap: 10px;
  z-index: 9999;
}}
.print-toolbar button {{
  padding: 8px 12px;
  font-weight: 800;
  cursor: pointer;
}}
</style>
</head>
<body>
<div class="print-toolbar">
  <button onclick="window.print()">Print to Office Printer</button>
  <button onclick="window.close()">Close</button>
  <span>BOL {found.get('bol','')}</span>
</div>
{content}
<script>
window.addEventListener("load", function(){{
  setTimeout(function(){{ window.print(); }}, 500);
}});
</script>
</body>
</html>"""

    return send_file(Path(path), as_attachment=False)

@app.route("/bol-view/<store_id>")
def bol_view(store_id):
    stores = read_json(STORES_FILE)
    queue = read_json(RMS_QUEUE_FILE)

    found = None
    for s in stores:
        if s.get("id") == store_id or clean(s.get("bol")) == store_id:
            found = s
            break

    if not found:
        for q in queue:
            if q.get("id") == store_id or clean(q.get("bol")) == store_id:
                found = q
                break

    if not found:
        abort(404)

    path = found.get("pdf_path") or found.get("printable_path") or ""
    if not path:
        # Try to find saved file by BOL number
        bol = safe_part(found.get("bol"))
        matches = list(BOL_DIR.rglob(f"*{bol}*.html")) + list(BOL_DIR.rglob(f"*{bol}*.pdf"))
        if matches:
            path = str(matches[0])

    if not path or not Path(path).exists():
        return render_template("bol_not_found.html", bol=found.get("bol", ""), path=path)

    return send_file(Path(path), as_attachment=False)

@app.route("/api/approve-review-force", methods=["POST"])
def api_approve_review_force():
    data = request.get_json(force=True)
    store_id = data.get("store_id")
    hub = data.get("hub")

    stores = read_json(STORES_FILE)
    updated = None

    for store in stores:
        if store.get("id") == store_id:
            store["hub"] = hub or store.get("hub") or "San Antonio"
            store["status"] = "Unassigned"
            store["review_reasons"] = []
            if not store.get("lat") or not store.get("lng"):
                store["lat"], store["lng"] = HUBS.get(store["hub"], HUBS["San Antonio"])["lat"], HUBS.get(store["hub"], HUBS["San Antonio"])["lng"]
            updated = store
            break

    write_json(STORES_FILE, stores)
    audit("Force Approve Need Review", {"store_id": store_id, "hub": hub})

    return jsonify({"ok": True, "store": updated})


@app.route("/api/rms/repair-bol/<bol_number>", methods=["POST"])
def api_rms_repair_bol(bol_number):
    settings_data = read_json(SETTINGS_FILE)
    username = clean(settings_data.get("rms_username"))
    password = clean(settings_data.get("rms_password"))
    login_url = settings_data.get("rms_login_url") or "https://rms.reusability.com/login"

    if not username or not password:
        return jsonify({"ok": False, "message": "Save RMS credentials first."})

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            page.locator('input[name="username"], input[type="email"], input[placeholder*="Username"], input').first.fill(username)
            page.locator('input[type="password"]').first.fill(password)
            page.get_by_role("button", name=re.compile("Sign In|Login", re.I)).click()
            page.wait_for_load_state("networkidle", timeout=60000)

            direct_print_url = f"https://rms.reusability.com/bills-of-lading/{clean(bol_number)}/print"
            page.goto(direct_print_url, wait_until="networkidle", timeout=60000)

            body_text = page.locator("body").inner_text(timeout=60000)
            html = page.content()
            item = extract_printable_bol_from_text(body_text, page.url)
            item["pdf_path"] = save_printable_snapshot(item, html)

            stores = read_json(STORES_FILE)
            replaced = False
            for idx, s in enumerate(stores):
                if clean(s.get("bol")) == clean(bol_number):
                    item["id"] = s.get("id", item["id"])
                    stores[idx] = item
                    replaced = True
                    break
            if not replaced:
                stores.append(item)

            write_json(STORES_FILE, stores)

            update_queue_from_item(item)

            browser.close()
            return jsonify({"ok": True, "item": item, "message": f"BOL {bol_number} repaired. Status: {item.get('status')}. Racks: {item.get('expected_racks')}"})
        except Exception as e:
            try:
                browser.close()
            except Exception:
                pass
            return jsonify({"ok": False, "message": str(e)[:300]})

@app.route("/rms-queue")
def rms_queue():
    queue = read_json(RMS_QUEUE_FILE)
    stores = read_json(STORES_FILE)
    imported_bols = {clean(s.get("bol")) for s in stores if clean(s.get("bol"))}

    for q in queue:
        if clean(q.get("bol")) in imported_bols and q.get("queue_status") != "Ignored":
            q["queue_status"] = "Imported"

    write_json(RMS_QUEUE_FILE, queue)
    return render_template("rms_queue.html", queue=queue)

@app.route("/api/rms/queue-refresh", methods=["POST"])
def api_rms_queue_refresh():
    result = scan_rms_queue_with_playwright(headless=False)

    history = read_json(SYNC_HISTORY_FILE)
    result.update({
        "id": str(uuid4()),
        "time": datetime.now().isoformat(timespec="seconds"),
        "action": "Refresh RMS Queue"
    })
    history.append(result)
    write_json(SYNC_HISTORY_FILE, history)
    audit("Refresh RMS Queue", result)

    return jsonify({"ok": result.get("ok", False), "result": result})

@app.route("/api/rms/queue-import-selected", methods=["POST"])
def api_rms_queue_import_selected():
    payload = request.get_json(force=True)
    bol_numbers = [clean(x) for x in payload.get("bols", []) if clean(x)]

    if not bol_numbers:
        return jsonify({"ok": False, "result": {"message": "Select at least one BOL."}})

    result = import_selected_queue_bols(bol_numbers, headless=False)

    history = read_json(SYNC_HISTORY_FILE)
    result.update({
        "id": str(uuid4()),
        "time": datetime.now().isoformat(timespec="seconds"),
        "action": "Import Selected RMS Queue"
    })
    history.append(result)
    write_json(SYNC_HISTORY_FILE, history)
    audit("Import Selected RMS Queue", result)

    return jsonify({"ok": result.get("ok", False), "result": result})

@app.route("/api/rms/queue-update-status", methods=["POST"])
def api_rms_queue_update_status():
    payload = request.get_json(force=True)
    bol_numbers = [clean(x) for x in payload.get("bols", []) if clean(x)]
    status = clean(payload.get("status")) or "New"

    queue = read_json(RMS_QUEUE_FILE)
    updated = 0
    for q in queue:
        if clean(q.get("bol")) in bol_numbers:
            q["queue_status"] = status
            q["updated_at"] = datetime.now().isoformat(timespec="seconds")
            updated += 1

    write_json(RMS_QUEUE_FILE, queue)
    audit("Update RMS Queue Status", {"status": status, "updated": updated})

    return jsonify({"ok": True, "updated": updated})

@app.route("/rms-sync")
def rms_sync():
    settings_data = read_json(SETTINGS_FILE)
    history = read_json(SYNC_HISTORY_FILE)
    return render_template("rms_sync.html", settings=settings_data, history=history)

@app.route("/api/rms/test-connection", methods=["POST"])
def api_rms_test_connection():
    history = read_json(SYNC_HISTORY_FILE)

    result = rms_login_with_playwright(headless=False)
    result.update({
        "id": str(uuid4()),
        "time": datetime.now().isoformat(timespec="seconds"),
        "action": "Test RMS Login"
    })

    settings_data = read_json(SETTINGS_FILE)
    settings_data["rms_connection_status"] = result.get("status", "Unknown")
    if result.get("ok"):
        settings_data["last_rms_login"] = datetime.now().isoformat(timespec="seconds")
    write_json(SETTINGS_FILE, settings_data)

    history.append(result)
    write_json(SYNC_HISTORY_FILE, history)
    audit("RMS Login Test", result)

    return jsonify({"ok": result.get("ok", False), "result": result})

@app.route("/api/rms/sync-open-bols", methods=["POST"])
def api_rms_sync_open_bols():
    history = read_json(SYNC_HISTORY_FILE)

    # Safety default: import all found BOLs. Set max_bols in JSON for testing if needed.
    payload = request.get_json(silent=True) or {}
    max_bols = int(payload.get("max_bols") or 0)

    result = rms_full_import_with_playwright(headless=False, max_bols=max_bols)
    result.update({
        "id": str(uuid4()),
        "time": datetime.now().isoformat(timespec="seconds"),
        "action": "Full RMS Multi-Page Import"
    })

    history.append(result)
    write_json(SYNC_HISTORY_FILE, history)
    audit("Full RMS Multi-Page Import", result)

    return jsonify({"ok": result.get("ok", False), "result": result})

@app.route("/settings", methods=["GET", "POST"])
def settings():
    settings_data = read_json(SETTINGS_FILE)
    message = ""
    if request.method == "POST":
        settings_data["rms_username"] = clean(request.form.get("rms_username"))
        settings_data["rms_login_url"] = clean(request.form.get("rms_login_url")) or "https://rms.reusability.com/login"
        settings_data["rms_bol_url"] = clean(request.form.get("rms_bol_url")) or "https://rms.reusability.com/bills-of-lading"
        settings_data["google_maps_api_key"] = clean(request.form.get("google_maps_api_key")) or settings_data.get("google_maps_api_key", "")
        settings_data["telnyx_api_key"] = clean(request.form.get("telnyx_api_key")) or settings_data.get("telnyx_api_key", "")
        settings_data["telnyx_from_number"] = clean(request.form.get("telnyx_from_number")) or settings_data.get("telnyx_from_number", "+12103529669")
        settings_data["public_eoms_url"] = clean(request.form.get("public_eoms_url")) or settings_data.get("public_eoms_url", "")
        settings_data["remember_rms_credentials"] = bool(request.form.get("remember_rms_credentials"))

        rms_password = clean(request.form.get("rms_password"))

        if settings_data["remember_rms_credentials"]:
            if rms_password:
                settings_data["rms_password"] = rms_password
                settings_data["rms_password_saved"] = True
            elif settings_data.get("rms_password"):
                settings_data["rms_password_saved"] = True
            else:
                settings_data["rms_password_saved"] = False
        else:
            settings_data["rms_password"] = ""
            settings_data["rms_password_saved"] = False
        write_json(SETTINGS_FILE, settings_data)
        audit("Update RMS Settings", {"username": settings_data["rms_username"], "password_saved": settings_data["rms_password_saved"]})
        message = "RMS settings saved. Automatic sync will be added later."
    return render_template("settings.html", settings=settings_data, message=message)


@app.route("/api/routes")
def api_routes():
    routes = read_json(ROUTES_FILE)
    return jsonify({"ok": True, "routes": routes})

@app.route("/api/route/<route_id>")
def api_route_detail(route_id):
    routes = read_json(ROUTES_FILE)
    for route in routes:
        if route.get("id") == route_id or route.get("route_number") == route_id:
            return jsonify({"ok": True, "route": route})
    return jsonify({"ok": False, "message": "Route not found."}), 404

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
        "mode_label": "Selection Order" if mode == "selection" else "Optimized Nearest Stop",
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




@app.route("/api/update-route-driver", methods=["POST"])
def api_update_route_driver():
    data = request.get_json(force=True)
    route_id = data.get("route_id")
    driver = clean(data.get("driver"))
    driver_phone = clean(data.get("driver_phone"))
    truck = clean(data.get("truck"))
    helper = clean(data.get("helper"))

    routes = read_json(ROUTES_FILE)
    stores = read_json(STORES_FILE)

    updated = None
    for route in routes:
        if route.get("id") == route_id or route.get("route_number") == route_id:
            route["driver"] = driver
            route["driver_phone"] = driver_phone
            route["truck"] = truck
            route["helper"] = helper
            route["updated_at"] = datetime.now().isoformat(timespec="seconds")
            updated = route

            route_store_ids = set(route.get("store_ids", []))
            for store in stores:
                if store.get("id") in route_store_ids:
                    store["assigned_driver"] = driver
                    store["driver_phone"] = driver_phone
                    store["truck"] = truck
                    store["helper"] = helper
                    store["status"] = "Assigned"
                    if store.get("pdf_path"):
                        store["pdf_path"] = move_pdf(store["pdf_path"], "Assigned")
            break

    if not updated:
        return jsonify({"ok": False, "message": "Route not found."})

    write_json(ROUTES_FILE, routes)
    write_json(STORES_FILE, stores)
    audit("Update Route Driver", {"route_id": route_id, "driver": driver, "driver_phone": driver_phone, "truck": truck, "helper": helper})

    return jsonify({"ok": True, "route": updated})

@app.route("/api/dispatch-route", methods=["POST"])
def api_dispatch_route():
    data = request.get_json(force=True)
    route_id = data.get("route_id")

    routes = read_json(ROUTES_FILE)
    stores = read_json(STORES_FILE)

    route = None
    for r in routes:
        if r.get("id") == route_id or r.get("route_number") == route_id:
            r["status"] = "Dispatched"
            r["dispatched_at"] = datetime.now().isoformat(timespec="seconds")
            route = r
            break

    if not route:
        return jsonify({"ok": False, "message": "Route not found."})

    route_store_ids = set(route.get("store_ids", []))
    for store in stores:
        if store.get("id") in route_store_ids:
            store["status"] = "Dispatched"
            store["assigned_driver"] = route.get("driver", "")
            store["driver_phone"] = route.get("driver_phone", "")
            store["dispatched_at"] = route.get("dispatched_at")
            if store.get("pdf_path"):
                store["pdf_path"] = move_pdf(store["pdf_path"], "Assigned")

    write_json(ROUTES_FILE, routes)
    write_json(STORES_FILE, stores)
    audit("Dispatch Route", {"route_id": route_id, "route_number": route.get("route_number")})

    return jsonify({"ok": True, "route": route})

@app.route("/api/complete-route", methods=["POST"])
def api_complete_route():
    data = request.get_json(force=True)
    route_id = data.get("route_id")

    routes = read_json(ROUTES_FILE)
    stores = read_json(STORES_FILE)

    route = None
    for r in routes:
        if r.get("id") == route_id or r.get("route_number") == route_id:
            r["status"] = "Completed"
            r["completed_at"] = datetime.now().isoformat(timespec="seconds")
            route = r
            break

    if not route:
        return jsonify({"ok": False, "message": "Route not found."})

    route_store_ids = set(route.get("store_ids", []))
    for store in stores:
        if store.get("id") in route_store_ids:
            store["status"] = "Completed"
            store["completed_at"] = route.get("completed_at")
            if store.get("pdf_path"):
                store["pdf_path"] = move_pdf(store["pdf_path"], "Completed")

    write_json(ROUTES_FILE, routes)
    write_json(STORES_FILE, stores)
    audit("Complete Route", {"route_id": route_id, "route_number": route.get("route_number")})

    return jsonify({"ok": True, "route": route})

@app.route("/route-view/<route_id>")
def route_view(route_id):
    routes = read_json(ROUTES_FILE)
    route = None
    for r in routes:
        if r.get("id") == route_id or r.get("route_number") == route_id:
            route = r
            break

    if not route:
        return "Route not found", 404

    return render_template("route_view.html", route=route)


@app.route("/api/send-route-sms", methods=["POST"])
def api_send_route_sms():
    data = request.get_json(force=True)
    route_id = data.get("route_id")

    settings_data = read_json(SETTINGS_FILE)
    telnyx_api_key = clean(settings_data.get("telnyx_api_key"))
    telnyx_from_number = clean(settings_data.get("telnyx_from_number")) or "+12103529669"
    public_eoms_url = clean(settings_data.get("public_eoms_url"))

    routes = read_json(ROUTES_FILE)
    route = None
    for r in routes:
        if r.get("id") == route_id or r.get("route_number") == route_id:
            route = r
            break

    if not route:
        return jsonify({"ok": False, "message": "Route not found."})

    driver_phone = clean(route.get("driver_phone"))
    if not driver_phone:
        return jsonify({"ok": False, "message": "Driver phone number is missing. Save driver phone first."})

    if not telnyx_api_key:
        return jsonify({"ok": False, "message": "Telnyx API key missing. Save it in Settings first."})

    if public_eoms_url:
        route_link = public_eoms_url.rstrip("/") + f"/route-view/{route.get('id')}"
    else:
        route_link = request.host_url.rstrip("/") + f"/route-view/{route.get('id')}"

    metrics = route.get("metrics", {})
    message = (
        f"EOMS Route {route.get('route_number')} assigned.\n"
        f"Driver: {route.get('driver') or ''}\n"
        f"Truck: {route.get('truck') or ''}\n"
        f"Helper: {route.get('helper') or ''}\n"
        f"Stops: {metrics.get('store_count', len(route.get('stops', [])))}\n"
        f"Racks: {metrics.get('racks', 0)}\n"
        f"Weight: {metrics.get('weight', 0)} lbs\n"
        f"Open route: {route_link}"
    )

    try:
        response = requests.post(
            "https://api.telnyx.com/v2/messages",
            headers={
                "Authorization": f"Bearer {telnyx_api_key}",
                "Content-Type": "application/json"
            },
            json={
                "from": telnyx_from_number,
                "to": driver_phone,
                "text": message
            },
            timeout=20
        )

        ok = 200 <= response.status_code < 300
        try:
            payload = response.json()
        except Exception:
            payload = {"raw": response.text[:500]}

        route["last_sms_status"] = "Sent" if ok else "Failed"
        route["last_sms_time"] = datetime.now().isoformat(timespec="seconds")
        route["last_sms_to"] = driver_phone
        route["last_sms_response"] = payload

        write_json(ROUTES_FILE, routes)
        audit("Send Route SMS", {
            "route_id": route_id,
            "route_number": route.get("route_number"),
            "to": driver_phone,
            "ok": ok,
            "status_code": response.status_code
        })

        if ok:
            return jsonify({"ok": True, "message": "Route SMS sent.", "route_link": route_link, "telnyx": payload})
        return jsonify({"ok": False, "message": f"Telnyx send failed: HTTP {response.status_code}", "telnyx": payload})

    except Exception as e:
        audit("Send Route SMS Error", {"route_id": route_id, "error": str(e)[:300]})
        return jsonify({"ok": False, "message": f"Telnyx error: {str(e)[:300]}"})

@app.route("/api/unassign-route", methods=["POST"])
def api_unassign_route():
    data = request.get_json(force=True)
    route_id = data.get("route_id")

    routes = read_json(ROUTES_FILE)
    stores = read_json(STORES_FILE)

    target_route = None
    remaining_routes = []

    for route in routes:
        if route.get("id") == route_id or route.get("route_number") == route_id:
            target_route = route
        else:
            remaining_routes.append(route)

    if not target_route:
        return jsonify({"ok": False, "message": "Route not found."})

    route_store_ids = set(target_route.get("store_ids", []))

    restored = 0
    for store in stores:
        if store.get("id") in route_store_ids:
            store["status"] = "Unassigned"
            store["assigned_driver"] = ""
            if store.get("pdf_path"):
                store["pdf_path"] = move_pdf(store["pdf_path"], "Imported")
            restored += 1

    write_json(STORES_FILE, stores)
    write_json(ROUTES_FILE, remaining_routes)
    audit("Unassign Entire Route", {"route_id": route_id, "restored": restored})

    return jsonify({"ok": True, "message": f"Route unassigned. {restored} stores returned to Dispatch Map."})


@app.route("/api/store-status", methods=["POST"])
def api_store_status():
    data = request.get_json(force=True)
    store_id = data.get("store_id")
    new_status = clean(data.get("status"))

    allowed = {"Need Review", "Unassigned", "Assigned", "Dispatched", "Completed"}
    if new_status not in allowed:
        return jsonify({"ok": False, "message": "Invalid status."})

    stores = read_json(STORES_FILE)
    updated = None

    for store in stores:
        if store.get("id") == store_id:
            store["status"] = new_status
            store["updated_at"] = datetime.now().isoformat(timespec="seconds")

            if new_status == "Unassigned":
                store["assigned_driver"] = ""
                if store.get("pdf_path"):
                    store["pdf_path"] = move_pdf(store["pdf_path"], "Imported")
            elif new_status == "Completed":
                if store.get("pdf_path"):
                    store["pdf_path"] = move_pdf(store["pdf_path"], "Completed")
            elif new_status == "Assigned":
                if store.get("pdf_path"):
                    store["pdf_path"] = move_pdf(store["pdf_path"], "Assigned")

            updated = store
            break

    if not updated:
        return jsonify({"ok": False, "message": "Store not found."})

    write_json(STORES_FILE, stores)
    audit("Update Store Status", {"store_id": store_id, "status": new_status})

    return jsonify({"ok": True, "store": updated})

@app.route("/api/unassign-store", methods=["POST"])
def api_unassign_store():
    data = request.get_json(force=True)
    store_id = data.get("store_id")
    stores = read_json(STORES_FILE)
    restored = None
    for store in stores:
        if store.get("id") == store_id:
            store["status"] = "Unassigned"
            store["assigned_driver"] = ""
            if store.get("pdf_path"):
                store["pdf_path"] = move_pdf(store["pdf_path"], "Imported")
            restored = store
            break

    routes = read_json(ROUTES_FILE)
    cleaned_routes = []
    for route in routes:
        route["store_ids"] = [sid for sid in route.get("store_ids", []) if sid != store_id]
        route["stops"] = [s for s in route.get("stops", []) if s.get("id") != store_id]
        if route.get("stops"):
            route["metrics"] = calculate_route_metrics(route["stops"], route.get("hub") or "San Antonio")
            cleaned_routes.append(route)

    write_json(STORES_FILE, stores)
    write_json(ROUTES_FILE, cleaned_routes)
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
        if store.get("id") == store_id:
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
