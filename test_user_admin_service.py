"""FT6: unit tests for eoms_modules/user_admin_service.py, extracted from
app.py's inline user-admin helper functions. Locks down the exact behavior
that existed inline before the move - no logic changed."""

import unittest

from eoms_modules.user_admin_service import (
    normalize_user_admin_role,
    normalize_user_admin_cities,
    user_admin_record_key,
    find_user_admin_record,
    active_admins_except,
    user_admin_summary,
    apply_user_admin_profile,
)


class NormalizeRoleTests(unittest.TestCase):
    def test_valid_role_passes_through(self):
        self.assertEqual(normalize_user_admin_role("Admin"), "Admin")

    def test_invalid_role_falls_back_to_dispatcher(self):
        self.assertEqual(normalize_user_admin_role("Superuser"), "Dispatcher")

    def test_empty_role_falls_back_to_dispatcher(self):
        self.assertEqual(normalize_user_admin_role(""), "Dispatcher")
        self.assertEqual(normalize_user_admin_role(None), "Dispatcher")


class NormalizeCitiesTests(unittest.TestCase):
    def test_admin_can_keep_all(self):
        self.assertEqual(normalize_user_admin_cities("Admin", ["All"]), ["All"])

    def test_non_privileged_role_strips_all(self):
        result = normalize_user_admin_cities("Dispatcher", ["All", "Houston"])
        self.assertEqual(result, ["Houston"])

    def test_non_privileged_role_with_only_all_falls_back_to_san_antonio(self):
        result = normalize_user_admin_cities("Driver", ["All"])
        self.assertEqual(result, ["San Antonio"])

    def test_unknown_cities_are_dropped(self):
        result = normalize_user_admin_cities("Dispatcher", ["Not A Real City", "Dallas"])
        self.assertEqual(result, ["Dallas"])

    def test_empty_selection_falls_back_to_san_antonio(self):
        self.assertEqual(normalize_user_admin_cities("Dispatcher", []), ["San Antonio"])


class RecordKeyTests(unittest.TestCase):
    def test_prefers_id_over_username(self):
        self.assertEqual(user_admin_record_key({"id": "abc", "username": "bob"}), "abc")

    def test_falls_back_to_username_when_no_id(self):
        self.assertEqual(user_admin_record_key({"username": "bob"}), "bob")

    def test_find_user_admin_record_matches_by_id_or_username(self):
        users = [{"id": "1", "username": "alice"}, {"id": "2", "username": "bob"}]
        self.assertEqual(find_user_admin_record(users, "2")["username"], "bob")
        self.assertEqual(find_user_admin_record(users, "alice")["id"], "1")
        self.assertIsNone(find_user_admin_record(users, "nobody"))


class ActiveAdminsExceptTests(unittest.TestCase):
    def test_excludes_target_and_inactive_and_non_admins(self):
        users = [
            {"id": "1", "role": "Admin", "active": True},
            {"id": "2", "role": "Admin", "active": True},
            {"id": "3", "role": "Admin", "active": False},
            {"id": "4", "role": "Dispatcher", "active": True},
        ]
        result = active_admins_except(users, {"id": "1"})
        self.assertEqual([u["id"] for u in result], ["2"])

    def test_no_target_still_lists_all_active_admins(self):
        users = [{"id": "1", "role": "Admin", "active": True}]
        result = active_admins_except(users, None)
        self.assertEqual([u["id"] for u in result], ["1"])


class UserAdminSummaryTests(unittest.TestCase):
    def test_summary_counts(self):
        users = [
            {"role": "Admin", "active": True},
            {"role": "Driver", "active": True},
            {"role": "Driver", "active": False},
        ]
        summary = user_admin_summary(users)
        self.assertEqual(summary, {"total": 3, "active": 2, "drivers": 2, "disabled": 1})


class ApplyUserAdminProfileTests(unittest.TestCase):
    class FakeForm(dict):
        """Minimal stand-in for a werkzeug ImmutableMultiDict: supports
        .get() (already via dict) and .getlist()."""
        def getlist(self, key):
            value = self.get(key)
            if value is None:
                return []
            return value if isinstance(value, list) else [value]

    def test_driver_role_keeps_driver_fields(self):
        user = {"username": "bob"}
        form = self.FakeForm({
            "role": "Driver",
            "display_name": "Bob Driver",
            "assigned_cities": ["Houston"],
            "phone": "555-1234",
        })
        result = apply_user_admin_profile(user, form)
        self.assertEqual(result["role"], "Driver")
        self.assertEqual(result["phone"], "555-1234")
        self.assertEqual(result["assigned_cities"], ["Houston"])

    def test_non_driver_role_strips_driver_only_fields(self):
        user = {"username": "bob", "phone": "555-1234", "driver_notes": "notes"}
        form = self.FakeForm({
            "role": "Dispatcher",
            "display_name": "Bob Dispatcher",
            "assigned_cities": ["Dallas"],
        })
        result = apply_user_admin_profile(user, form)
        self.assertNotIn("phone", result)
        self.assertNotIn("driver_notes", result)

    def test_display_name_falls_back_to_existing_then_username(self):
        user = {"username": "bob", "display_name": "Existing Name"}
        form = self.FakeForm({"role": "Dispatcher", "assigned_cities": ["Dallas"]})
        result = apply_user_admin_profile(user, form)
        self.assertEqual(result["display_name"], "Existing Name")


if __name__ == "__main__":
    unittest.main()
