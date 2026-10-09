"""Read-only weekly closeout totals using owner-entered piece rates."""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")


def pay_week(value=None, today=None):
    today = today or datetime.now(CENTRAL).date()
    anchor = date.fromisoformat(value) if value else today - timedelta(days=today.weekday() + 7)
    monday = anchor - timedelta(days=anchor.weekday())
    return monday, monday + timedelta(days=6)


def local_date(value):
    try:
        stamp = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return stamp.astimezone(CENTRAL).date() if stamp.tzinfo else stamp.date()
    except ValueError:
        return None


def piece_rate(value):
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Enter a valid rate per piece.")
    if not number.is_finite() or number < 0 or number.as_tuple().exponent < -4:
        raise ValueError("Rate must be zero or greater, with up to four decimal places.")
    return number


def build_weekly_pay(stores, users, week=None, rates=None, today=None):
    start, end = pay_week(week, today)
    rates = rates or {}
    drivers = {u.get("username"):u.get("display_name") or u.get("username") for u in users if u.get("role") == "Driver"}
    aliases = {}
    for username, label in drivers.items():
        if list(drivers.values()).count(label) == 1:
            aliases[label] = username
    groups = {}
    seen = set()
    for row in stores:
        worked = local_date(row.get("completed_at"))
        if not worked or not start <= worked <= end:
            continue
        identity = row.get("id")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        driver = row.get("assigned_driver") or row.get("driver_counts_saved_by") or row.get("completed_by") or "Unassigned"
        driver = aliases.get(driver, driver)
        group = groups.setdefault(driver, {"driver":driver,"name":drivers.get(driver, driver),"pieces":0,"closed_bols":0,"pending_bols":0,"missing_pieces":0,"bols":[]})
        approved = row.get("dispatcher_closeout_status") == "Closed"
        pieces = None
        if approved:
            group["closed_bols"] += 1
            try:
                value = Decimal(str(row.get("warehouse_verified_pieces")))
                if not value.is_finite() or value < 0 or value != value.to_integral_value():
                    raise InvalidOperation
                pieces = int(value)
                group["pieces"] += pieces
            except (InvalidOperation, ValueError):
                group["missing_pieces"] += 1
        else:
            group["pending_bols"] += 1
        group["bols"].append({"id":row.get("id"),"bol":row.get("bol"),"store":row.get("store_name") or row.get("store") or "Pickup","worked":worked.isoformat(),"pieces":pieces,"approved":approved})
    total = Decimal("0")
    missing_rates = 0
    for group in groups.values():
        rate = piece_rate(rates.get(group["driver"]))
        group["rate"] = str(rate) if rate is not None else ""
        amount = (rate * group["pieces"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if rate is not None and not group["missing_pieces"] else None
        group["amount"] = str(amount) if amount is not None else None
        if amount is not None:
            total += amount
        elif group["closed_bols"]:
            missing_rates += 1
        group["bols"].sort(key=lambda row:(row["worked"],str(row["bol"])))
    return {"start":start.isoformat(),"end":end.isoformat(),"verify":(start+timedelta(days=9)).isoformat(),"send":(start+timedelta(days=10)).isoformat(),"payday":(start+timedelta(days=11)).isoformat(),"drivers":sorted(groups.values(),key=lambda g:g["name"]),"total":str(total.quantize(Decimal("0.01"))),"incomplete_totals":missing_rates,"pending_bols":sum(g["pending_bols"] for g in groups.values())}
