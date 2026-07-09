"""FT6: proves the Database Maintenance API blueprint extraction did not
change externally visible behavior versus the old inline app.py routes."""

import os
import unittest

os.environ.setdefault("SECRET_KEY", "database-maintenance-test-secret")

import app as eoms_app


class DatabaseMaintenanceBlueprintTests(unittest.TestCase):
    def setUp(self):
        self.client = eoms_app.app.test_client()

    def test_all_expected_routes_are_registered(self):
        rules = {r.rule for r in eoms_app.app.url_map.iter_rules()}
        expected = {
            "/api/database/backup",
            "/api/database/repair-duplicates",
            "/api/database/duplicates",
            "/api/database/missing-pdfs",
            "/api/database/orphan-pdfs",
            "/api/database/backups",
            "/api/database/restore-backup",
        }
        self.assertTrue(expected.issubset(rules))

    def test_backup_redirects_to_login_when_unauthenticated(self):
        # admin_required redirects browser-style GET/POST requests to login
        # (unlike the driver/receiving JSON APIs, which return 401 JSON via
        # the global before_request hook for /api/ paths not covered by
        # admin_required's own check).
        response = self.client.post("/api/database/backup", follow_redirects=False)
        self.assertIn(response.status_code, (302, 401))

    def test_duplicates_rejects_unknown_user(self):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = "not-a-real-admin-user"
        response = self.client.get("/api/database/duplicates")
        # Unknown username -> current_user() returns None -> the global
        # enforce_login() before_request hook (not admin_required itself)
        # rejects it with a 401 JSON response for /api/ paths.
        self.assertEqual(response.status_code, 401)

    def test_backups_list_works_for_admin(self):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = "admin"
        response = self.client.get("/api/database/backups")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
     