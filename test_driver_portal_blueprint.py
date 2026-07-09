"""FT6 phase 2: proves the Driver Portal blueprint extraction (routes/driver_portal.py)
did not change any externally visible behavior versus the old inline app.py routes.

This is intentionally black-box: it hits the routes through the real Flask
test client and checks the same auth/response contract the old inline routes
had, rather than importing the blueprint module directly.
"""

import os
import unittest

os.environ.setdefault("SECRET_KEY", "driver-blueprint-test-secret")

import app as eoms_app


class DriverPortalBlueprintTests(unittest.TestCase):
    def setUp(self):
        self.client = eoms_app.app.test_client()

    def test_driver_routes_are_registered_on_the_app(self):
        rules = {r.rule for r in eoms_app.app.url_map.iter_rules()}
        expected = {
            "/driver",
            "/api/driver/accept-route",
            "/api/driver/decline-route",
            "/api/driver/save-counts",
            "/api/driver/save-exception",
            "/api/driver/complete-stop",
            "/api/driver/complete",
        }
        self.assertTrue(expected.issubset(rules))

    def test_driver_page_redirects_to_login_when_unauthenticated(self):
        # enforce_login() is a global @app.before_request hook on `app`, not a
        # per-blueprint decorator, so it must still apply to blueprint routes.
        response = self.client.get("/driver", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))

    def test_driver_api_returns_401_json_when_unauthenticated(self):
        response = self.client.post("/api/driver/accept-route", json={"route_id": "x"})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_driver_accept_route_missing_route_returns_404_when_authenticated(self):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = "admin"
        response = self.client.post("/api/driver/accept-route", json={"route_id": "does-not-exist"})
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
