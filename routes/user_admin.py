"""User / Driver administration blueprint.

FT6 blueprint split: relocates Flask routing/glue code out of app.py for
all three user-management surfaces (the legacy /users pages, the newer
/user-admin pages, and the /drivers directory). Pure business logic now
lives in eoms_modules.user_admin_service; shared auth primitives
(users_payload, save_users_payload, current_user, etc.) are imported from
app, exactly like every other FT6 blueprint does. No behavior changed.
"""

from datetime import datetime
from uuid import uuid4

from flask import Blueprint, jsonify, redirect, render_template, request, session

from app import (
    ROUTES_FILE,
    read_json,
    filter_routes_for_user,
    users_payload,
    save_users_payload,
    current_user,
    current_role,
    is_admin,
    user_allowed_city_values,
    hash_password,
    audit,
    clean,
    admin_required,
    dispatch_required,
)
from eoms_modules.user_admin_service import (
    USER_ADMIN_ROLES,
    USER_ADMIN_CITY_OPTIONS,
    normalize_user_admin_role,
    normalize_user_admin_cities,
    user_admin_record_key,
    find_user_admin_record,
    active_admins_except,
    user_admin_summary,
    apply_user_admin_profile,
)

user_admin_bp = Blueprint("user_admin", __name__)


def _user_admin_status_redirect(status):
    return redirect(f"/user-admin?status={status}")


# ---------------------------------------------------------------------------
# Drivers directory (subset view for dispatch/admin)
# ---------------------------------------------------------------------------

@user_admin_bp.route("/api/drivers")
@dispatch_required
def api_drivers():
    users = users_payload().get("users", [])
    drivers = []
    allowed_cities = set(user_allowed_city_values())
    for user in users:
        if not user.get("active", True):
            continue
        role = (user.get("role") or "").lower()
        if role == "driver":
            driver_cities = set(user.get("assigned_cities") or [])
            if current_role() == "Dispatcher" and "All" not in allowed_cities and not (allowed_cities & driver_cities):
                continue
            drivers.append({
                "name": user.get("display_name") or user.get("username"),
                "username": user.get("username"),
                "role": user.get("role", "Dispatcher"),
                "phone": user.get("phone", ""),
                "cities": user.get("assigned_cities", []),
            })
    return jsonify({"ok": True, "drivers": drivers})


@user_admin_bp.route("/drivers")
@dispatch_required
def drivers_directory():
    drivers = [u for u in users_payload().get("users", []) if (u.get("role") or "").lower() == "driver"]
    allowed_cities = set(user_allowed_city_values())
    if current_role() == "Dispatcher" and "All" not in allowed_cities:
        drivers = [u for u in drivers if allowed_cities & set(u.get("assigned_cities") or [])]
    routes = filter_routes_for_user(read_json(ROUTES_FILE))
    driver_phones = {}
    for driver in drivers:
        phone = clean(driver.get("phone"))
        if phone:
            driver_phones[clean(driver.get("username"))] = phone
            driver_phones[clean(driver.get("display_name"))] = phone
    route_counts = {}
    for route in routes:
        driver_name = clean(route.get("driver"))
        if driver_name:
            route_counts[driver_name] = route_counts.get(driver_name, 0) + 1
            if not clean(route.get("driver_phone")):
                route["driver_phone"] = driver_phones.get(driver_name, "")
    return render_template(
        "drivers.html", drivers=drivers, routes=routes,
        route_counts=route_counts, city_options=["All", "San Antonio", "Houston", "Dallas"],
        can_manage=is_admin()
    )


@user_admin_bp.route("/drivers/create", methods=["POST"])
@admin_required
def drivers_create():
    username = clean(request.form.get("username"))
    display_name = clean(request.form.get("display_name"))
    password = request.form.get("password") or ""
    phone = clean(request.form.get("phone"))
    assigned_cities = request.form.getlist("assigned_cities") or ["San Antonio"]
    if "All" in assigned_cities:
        assigned_cities = ["San Antonio", "Houston", "Dallas"]
    data = users_payload()
    users = data.get("users", [])
    if not username or not display_name or not password or not phone:
        return redirect("/drivers?error=missing")
    if any(clean(u.get("username")) == username for u in users):
        return redirect("/drivers?error=duplicate")
    users.append({
        "id": str(uuid4()), "username": username, "display_name": display_name,
        "password": hash_password(password), "phone": phone, "role": "Driver",
        "assigned_cities": assigned_cities, "active": True,
        "created_at": datetime.now().isoformat(timespec="seconds")
    })
    data["users"] = users
    save_users_payload(data)
    audit("Create Driver", {"username": username, "display_name": display_name, "phone": phone, "assigned_cities": assigned_cities})
    return redirect("/drivers?created=1")


@user_admin_bp.route("/drivers/update/<driver_id>", methods=["POST"])
@admin_required
def drivers_update(driver_id):
    data = users_payload()
    updated = None
    for user in data.get("users", []):
        if (user.get("id") == driver_id or user.get("username") == driver_id) and (user.get("role") or "").lower() == "driver":
            user["display_name"] = clean(request.form.get("display_name")) or user.get("display_name") or user.get("username")
            user["phone"] = clean(request.form.get("phone")) or user.get("phone", "")
            user["assigned_cities"] = request.form.getlist("assigned_cities") or user.get("assigned_cities", ["San Antonio"])
            user["active"] = bool(request.form.get("active"))
            password = request.form.get("password") or ""
            if password:
                user["password"] = hash_password(password)
            user["updated_at"] = datetime.now().isoformat(timespec="seconds")
            updated = user
            break
    save_users_payload(data)
    if updated:
        audit("Update Driver", {"username": updated.get("username"), "active": updated.get("active"), "assigned_cities": updated.get("assigned_cities")})
    return redirect("/drivers")


@user_admin_bp.route("/drivers/delete/<driver_id>", methods=["POST"])
@admin_required
def drivers_delete(driver_id):
    data = users_payload()
    users = data.get("users", [])
    target = next(
        (
            u for u in users
            if (u.get("id") == driver_id or u.get("username") == driver_id)
            and (u.get("role") or "").lower() == "driver"
        ),
        None,
    )
    if not target:
        audit("Delete Driver Failed", {"driver_id": driver_id, "reason": "not found"})
        return redirect("/drivers?error=notfound")

    data["users"] = [
        u for u in users
        if not (u.get("id") == target.get("id") or u.get("username") == target.get("username"))
    ]
    save_users_payload(data)
    audit("Delete Driver", {
        "username": target.get("username"),
        "display_name": target.get("display_name"),
        "phone": target.get("phone"),
    })
    return redirect("/drivers?deleted=1")


# ---------------------------------------------------------------------------
# User Admin (role/city-aware admin console with last-admin protection)
# ---------------------------------------------------------------------------

@user_admin_bp.route("/user-admin")
@admin_required
def user_admin_workspace():
    users = users_payload().get("users", [])
    users = sorted(users, key=lambda user: clean(user.get("username")).lower())
    return render_template(
        "user_admin.html",
        users=users,
        roles=USER_ADMIN_ROLES,
        city_options=USER_ADMIN_CITY_OPTIONS,
        summary=user_admin_summary(users),
        status=clean(request.args.get("status")),
    )


@user_admin_bp.route("/user-admin/create", methods=["POST"])
@admin_required
def user_admin_create():
    data = users_payload()
    users = data.get("users", [])
    username = clean(request.form.get("username")).lower()
    password = request.form.get("password") or ""

    if not username or not password:
        return _user_admin_status_redirect("missing")
    if any(clean(user.get("username")).lower() == username for user in users):
        return _user_admin_status_redirect("duplicate")

    now = datetime.now().isoformat(timespec="seconds")
    user = {
        "id": str(uuid4()),
        "username": username,
        "password": hash_password(password),
        "active": True,
        "created_at": now,
        "created_by": session.get("username"),
    }
    apply_user_admin_profile(user, request.form)
    users.append(user)
    data["users"] = users
    save_users_payload(data)
    audit("Create User", {"username": username, "role": user.get("role"), "assigned_cities": user.get("assigned_cities", [])})
    return _user_admin_status_redirect("created")


@user_admin_bp.route("/user-admin/update/<user_id>", methods=["POST"])
@admin_required
def user_admin_update(user_id):
    data = users_payload()
    users = data.get("users", [])
    user = find_user_admin_record(users, user_id)
    if not user:
        return _user_admin_status_redirect("notfound")

    current = current_user() or {}
    wants_active = bool(request.form.get("active"))
    new_role = normalize_user_admin_role(request.form.get("role"))
    is_self = user_admin_record_key(user) == user_admin_record_key(current) or clean(user.get("username")) == clean(current.get("username"))
    removing_last_admin = (
        user.get("role") == "Admin"
        and user.get("active", True)
        and (new_role != "Admin" or not wants_active)
        and not active_admins_except(users, user)
    )
    if is_self and not wants_active:
        return _user_admin_status_redirect("self")
    if removing_last_admin:
        return _user_admin_status_redirect("lastadmin")

    apply_user_admin_profile(user, request.form)
    user["active"] = wants_active
    new_password = request.form.get("password") or ""
    if new_password:
        user["password"] = hash_password(new_password)
    now = datetime.now().isoformat(timespec="seconds")
    user["updated_at"] = now
    user["updated_by"] = session.get("username")
    if not wants_active:
        user["disabled_at"] = user.get("disabled_at") or now
        user["disabled_by"] = user.get("disabled_by") or session.get("username")
    else:
        user.pop("disabled_at", None)
        user.pop("disabled_by", None)

    save_users_payload(data)
    audit("Update User", {"username": user.get("username"), "role": user.get("role"), "active": user.get("active", True)})
    return _user_admin_status_redirect("updated")


@user_admin_bp.route("/user-admin/toggle/<user_id>", methods=["POST"])
@admin_required
def user_admin_toggle(user_id):
    data = users_payload()
    users = data.get("users", [])
    user = find_user_admin_record(users, user_id)
    if not user:
        return _user_admin_status_redirect("notfound")

    current = current_user() or {}
    is_self = user_admin_record_key(user) == user_admin_record_key(current) or clean(user.get("username")) == clean(current.get("username"))
    next_active = not user.get("active", True)
    if is_self and not next_active:
        return _user_admin_status_redirect("self")
    if user.get("role") == "Admin" and user.get("active", True) and not active_admins_except(users, user):
        return _user_admin_status_redirect("lastadmin")

    now = datetime.now().isoformat(timespec="seconds")
    user["active"] = next_active
    user["updated_at"] = now
    user["updated_by"] = session.get("username")
    if next_active:
        user.pop("disabled_at", None)
        user.pop("disabled_by", None)
    else:
        user["disabled_at"] = now
        user["disabled_by"] = session.get("username")

    save_users_payload(data)
    audit("Toggle User Active", {"username": user.get("username"), "active": next_active})
    return _user_admin_status_redirect("enabled" if next_active else "disabled")


# ---------------------------------------------------------------------------
# Legacy /users pages (older, simpler admin surface - still active)
# ---------------------------------------------------------------------------

@user_admin_bp.route("/users")
@admin_required
def users_admin():
    data = users_payload()
    city_options = ["All", "San Antonio", "Houston", "Dallas", "Austin", "Killeen", "Waco", "Corpus Christi", "South Texas"]
    return render_template("users.html", users=data.get("users", []), city_options=city_options)


@user_admin_bp.route("/users/create", methods=["POST"])
@admin_required
def users_create():
    username = clean(request.form.get("username"))
    password = request.form.get("password") or ""
    role = clean(request.form.get("role")) or "Dispatcher"
    if role not in {"Admin", "Operations Manager", "Dispatcher", "Driver"}:
        role = "Dispatcher"
    assigned_cities = request.form.getlist("assigned_cities") or ["San Antonio"]
    data = users_payload()
    users = data.get("users", [])
    if not username or not password:
        return redirect("/users")
    if any(u.get("username") == username for u in users):
        return redirect("/users")
    if role not in {"Admin", "Operations Manager"} and "All" in assigned_cities:
        assigned_cities = [c for c in assigned_cities if c != "All"] or ["San Antonio"]
    users.append({"id": str(uuid4()), "username": username, "password": hash_password(password), "role": role, "assigned_cities": assigned_cities, "active": True, "created_at": datetime.now().isoformat(timespec="seconds")})
    data["users"] = users
    save_users_payload(data)
    audit("Create User", {"username": username, "role": role, "assigned_cities": assigned_cities})
    return redirect("/users")


@user_admin_bp.route("/users/update/<user_id>", methods=["POST"])
@admin_required
def users_update(user_id):
    data = users_payload()
    for user in data.get("users", []):
        if user.get("id") == user_id or user.get("username") == user_id:
            role = clean(request.form.get("role")) or user.get("role", "Dispatcher")
            user["role"] = role if role in {"Admin", "Operations Manager", "Dispatcher", "Driver"} else "Dispatcher"
            user["assigned_cities"] = request.form.getlist("assigned_cities") or user.get("assigned_cities", ["San Antonio"])
            if user["role"] not in {"Admin", "Operations Manager"} and "All" in user["assigned_cities"]:
                user["assigned_cities"] = [c for c in user["assigned_cities"] if c != "All"] or ["San Antonio"]
            user["active"] = bool(request.form.get("active"))
            new_password = request.form.get("password") or ""
            if new_password:
                user["password"] = hash_password(new_password)
            user["updated_at"] = datetime.now().isoformat(timespec="seconds")
            break
    save_users_payload(data)
    return redirect("/users")


@user_admin_bp.route("/users/delete/<user_id>", methods=["POST"])
@admin_required
def users_delete(user_id):
    data = users_payload()
    users = data.get("users", [])
    current = current_user() or {}
    target = next((u for u in users if u.get("id") == user_id or u.get("username") == user_id), None)

    if not target:
        audit("Delete User Failed", {"user_id": user_id, "reason": "not found"})
        return redirect("/users")

    # Prevent the current administrator from deleting their own active session.
    if target.get("id") == current.get("id") or target.get("username") == current.get("username"):
        audit("Delete User Blocked", {"username": target.get("username"), "reason": "self delete"})
        return redirect("/users")

    # Prevent deleting the last active admin account.
    active_admins = [
        u for u in users
        if u.get("role") == "Admin" and u.get("active", True)
        and not (u.get("id") == target.get("id") or u.get("username") == target.get("username"))
    ]
    if target.get("role") == "Admin" and target.get("active", True) and not active_admins:
        audit("Delete User Blocked", {"username": target.get("username"), "reason": "last active admin"})
        return redirect("/users")

    data["users"] = [
        u for u in users
        if not (u.get("id") == target.get("id") or u.get("username") == target.get("username"))
    ]
    save_users_payload(data)
    audit("Delete User", {"username": target.get("username"), "role": target.get("role")})
    return redirect("/users")
