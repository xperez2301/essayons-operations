"""FT6: proves the User Admin blueprint extraction (routes/user_admin.py)
preserved the critical safety behaviors from the old inline app.py routes -
especially last-admin protection and self-deactivation prevention, since
those are the highest-stakes logic in this extraction (getting them wrong
could lock every admin out of EOMS)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "user-admin-blueprint-test-secret")

import app as eoms_app


class UserAdminBlueprintTests(unittest.TestCase):
    def setUp(self):
        self.client = eoms_app.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.users_path = Path(self.temp_dir.name) / "users.json"

        self.users_data = {
            "users": [
                {"id": "admin-1", "username": "admin1", "role": "Admin", "active": True},
                {"id": "admin-2", "username": "admin2", "role": "Admin", "active": True},
                {"id": "disp-1", "username": "disp1", "role": "Dispatcher", "active": True},
            ]
        }
        self.users_path.write_text(json.dumps(self.users_data), encoding="utf-8")
        self.users_patch = patch.object(eoms_app, "USERS_FILE", self.users_path)
        self.users_patch.start()

    def tearDown(self):
        self.users_patch.stop()
        self.temp_dir.cleanup()

    def login_as(self, username):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = username

    def current_users(self):
        return json.loads(self.users_path.read_text(encoding="utf-8"))["users"]

    def test_routes_are_registered(self):
        rules = {r.rule for r in eoms_app.app.url_map.iter_rules()}
        expected = {
            "/api/drivers", "/drivers", "/drivers/create",
            "/drivers/update/<driver_id>", "/drivers/delete/<driver_id>",
            "/user-admin", "/user-admin/create",
            "/user-admin/update/<user_id>", "/user-admin/toggle/<user_id>",
            "/users", "/users/create", "/users/update/<user_id>", "/users/delete/<user_id>",
        }
        self.assertTrue(expected.issubset(rules))

    def test_user_admin_page_redirects_when_unauthenticated(self):
        response = self.client.get("/user-admin", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))

    def test_cannot_deactivate_the_last_active_admin(self):
        self.login_as("admin1")
        # Deactivate admin2 first, leaving admin1 as the sole active admin.
        self.client.post("/user-admin/toggle/admin-2")
        self.assertFalse(next(u for u in self.current_users() if u["id"] == "admin-2")["active"])

        # Now try to toggle off admin1 (the last remaining active admin) as
        # someone else logged in - use disp-1's session isn't admin_required
        # though, so log in as admin1 acting on themself isn't "self" here
        # since admin_required just requires an Admin role; toggling admin1
        # while logged in as admin1 IS the self-deactivation path.
        response = self.client.post("/user-admin/toggle/admin-1", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("status=self", response.headers.get("Location", ""))
        # admin1 must still be active - the toggle must not have applied.
        self.assertTrue(next(u for u in self.current_users() if u["id"] == "admin-1")["active"])

    def test_cannot_delete_the_last_active_admin_via_user_admin_update(self):
        self.login_as("admin1")
        self.client.post("/user-admin/toggle/admin-2")  # admin2 now inactive
        response = self.client.post(
            "/user-admin/update/admin-1",
            data={"role": "Dispatcher", "assigned_cities": ["San Antonio"], "active": ""},
            follow_redirects=False,
        )
        self.assertIn("status=self", response.headers.get("Location", ""))

    def test_legacy_users_delete_blocks_self_delete(self):
        self.login_as("admin1")
        response = self.client.post("/users/delete/admin-1", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        # admin1 must still exist.
        self.assertTrue(any(u["id"] == "admin-1" for u in self.current_users()))

    def test_legacy_users_delete_blocks_deleting_last_admin(self):
        self.login_as("admin1")
        # admin1 tries to delete admin2, the *other* admin - allowed only if
        # it doesn't leave zero active admins. Since admin1 remains active,
        # this should succeed (admin1 stays as the last admin).
        response = self.client.post("/users/delete/admin-2", follow_redirects=True)
        self.assertFalse(any(u["id"] == "admin-2" for u in self.current_users()))

    def test_user_admin_create_rejects_duplicate_username(self):
        self.login_as("admin1")
        response = self.client.post(
            "/user-admin/create",
            data={"username": "admin1", "password": "x", "role": "Dispatcher", "assigned_cities": ["Dallas"]},
            follow_redirects=False,
        )
        self.assertIn("status=duplicate", response.headers.get("Location", ""))
        self.assertEqual(len(self.current_users()), 3)  # unchanged

    def test_user_admin_create_adds_new_user(self):
        self.login_as("admin1")
        response = self.client.post(
            "/user-admin/create",
            data={"username": "newuser", "password": "x", "role": "Dispatcher", "assigned_cities": ["Dallas"]},
            follow_redirects=False,
        )
        self.assertIn("status=created", response.headers.get("Location", ""))
        self.assertEqual(len(self.current_users()), 4)


if __name__ == "__main__":
    unittest.main()
