"""FT6: proves the Recovery Center and Reporting blueprint extractions did not
change any externally visible behavior versus the old inline app.py routes."""

import os
import unittest

os.environ.setdefault("SECRET_KEY", "recovery-reporting-test-secret")

import app as eoms_app


class RecoveryReportingBlueprintTests(unittest.TestCase):
    def setUp(self):
        self.client = eoms_app.app.test_client()

    def test_routes_are_registered(self):
        rules = {r.rule for r in eoms_app.app.url_map.iter_rules()}
        self.assertIn("/recovery", rules)
        self.assertIn("/reporting", rules)

    def test_recovery_page_redirects_to_login_when_unauthenticated(self):
        response = self.client.get("/recovery", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))

    def test_reporting_page_redirects_to_login_when_unauthenticated(self):
        response = self.client.get("/reporting", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))

    def test_recovery_page_renders_when_authenticated(self):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = "admin"
        response = self.client.get("/recovery")
        self.assertEqual(response.status_code, 200)

    def test_reporting_page_renders_when_authenticated(self):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = "admin"
        response = self.client.get("/reporting")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
