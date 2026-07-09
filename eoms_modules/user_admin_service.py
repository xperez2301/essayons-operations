"""User Admin business logic.

FT6: extracted from app.py (where these were plain module-level helper
functions used only by the /user-admin/* routes) into a proper service
module, following the same shape as the other eoms_modules/*_service.py
files. No behavior changed - this is the exact same logic that lived
inline in app.py, just relocated and given a home.
"""

from typing import Optional


def clean(value):
    return "" if value is None else str(value).strip()


USER_ADMIN_ROLES = ("Admin", "Operations Manager", "Dispatcher", "Driver")
USER_ADMIN_CITY_OPTIONS = ("All", "San Antonio", "Houston", "Dallas", "Austin", "Killeen", "Waco", "Corpus Christi", "South Texas")
DRIVER_PROFILE_FIELDS = ("phone", "driver_license", "emergency_contact", "driver_notes")


def normalize_user_admin_role(role):
    role = clean(role) or "Dispatcher"
    return role if role in USER_ADMIN_ROLES else "Dispatcher"


def normalize_user_admin_cities(role, selected):
    cities = [clean(city) for city in selected if clean(city) in USER_ADMIN_CITY_OPTIONS]
    if not cities:
        cities = ["San Antonio"]
    if role not in {"Admin", "Operations Manager"} and "All" in cities:
        cities = [city for city in cities if city != "All"] or ["San Antonio"]
    return cities


def user_admin_record_key(user):
    return clean(user.get("id")) or clean(user.get("username"))


def find_user_admin_record(users, user_id):
    lookup = clean(user_id)
    return next(
        (
            user for user in users
            if clean(user.get("id")) == lookup or clean(user.get("username")) == lookup
        ),
        None,
    )


def active_admins_except(users, target: Optional[dict] = None):
    target_key = user_admin_record_key(target or {})
    return [
        user for user in users
        if user.get("role") == "Admin"
        and user.get("active", True)
        and user_admin_record_key(user) != target_key
    ]


def user_admin_summary(users):
    return {
        "total": len(users),
        "active": sum(1 for user in users if user.get("active", True)),
        "drivers": sum(1 for user in users if user.get("role") == "Driver"),
        "disabled": sum(1 for user in users if not user.get("active", True)),
    }


def apply_user_admin_profile(user, form):
    role = normalize_user_admin_role(form.get("role"))
    user["display_name"] = clean(form.get("display_name")) or clean(user.get("display_name")) or clean(user.get("username"))
    user["role"] = role
    user["assigned_cities"] = normalize_user_admin_cities(role, form.getlist("assigned_cities"))
    if role == "Driver":
        for field in DRIVER_PROFILE_FIELDS:
            user[field] = clean(form.get(field))
    else:
        for field in DRIVER_PROFILE_FIELDS:
            user.pop(field, None)
    return user
