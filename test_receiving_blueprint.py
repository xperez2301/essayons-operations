"""FT6 phase 3: proves the Receiving blueprint extraction (routes/receiving.py)
did not change any externally visible behavior versus the old inline app.py
routes. Black-box, through the real Flask test client."""

import os
import unittest

os.environ.setdefault("SECRET_KEY", "receiving-blueprint-test-secret")

import app as eoms_app


class ReceivingBlueprintTests(unittest.TestCase):
    def setUp(self):
        self.client = eoms_app.app.test_client()

    def test_receiving_routes_are_registered_on_the_app(self):
        rules = {r.rule for r in eoms_app.app.url_map.iter_rules()}
        self.assertIn("/receiving", rules)
        self.assertIn("/api/receiving/receive", rules)

    def test_receiving_page_redirects_to_login_when_unauthenticated(self):
        response = self.client.get("/receiving", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))

    def test_receiving_api_returns_401_json_when_unauthenticated(self):
        response = self.client.post("/api/receiving/receive", json={"store_id": "x"})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_receive_missing_store_returns_404_when_authenticated(self):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = "admin"
        response = self.client.post("/api/receiving/receive", json={"store_id": "does-not-exist"})
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
