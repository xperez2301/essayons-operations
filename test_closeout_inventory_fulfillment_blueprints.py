"""FT6: proves the Dispatcher Closeout, Inventory, and Fulfillment blueprint
extractions did not change any externally visible behavior versus the old
inline app.py routes. Black-box, through the real Flask test client."""

import os
import unittest

os.environ.setdefault("SECRET_KEY", "closeout-inventory-fulfillment-test-secret")

import app as eoms_app


class RegisteredRoutesTests(unittest.TestCase):
    def test_all_expected_routes_are_registered(self):
        rules = {r.rule for r in eoms_app.app.url_map.iter_rules()}
        expected = {
            "/dispatcher-closeout",
            "/api/dispatcher/closeout",
            "/inventory",
            "/api/inventory/adjust",
            "/fulfillment",
            "/api/fulfillment/reserve",
            "/api/fulfillment/ship",
        }
        self.assertTrue(expected.issubset(rules))


class AuthEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.client = eoms_app.app.test_client()

    def test_dispatcher_closeout_page_redirects_when_unauthenticated(self):
        response = self.client.get("/dispatcher-closeout", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))

    def test_dispatcher_closeout_api_returns_401_when_unauthenticated(self):
        response = self.client.post("/api/dispatcher/closeout", json={"store_id": "x"})
        self.assertEqual(response.status_code, 401)

    def test_inventory_page_redirects_when_unauthenticated(self):
        response = self.client.get("/inventory", follow_redirects=False)
        self.assertEqual(response.status_code, 302)

    def test_inventory_adjust_returns_401_when_unauthenticated(self):
        response = self.client.post("/api/inventory/adjust", json={"component": "racks", "amount": 1})
        self.assertEqual(response.status_code, 401)

    def test_fulfillment_page_redirects_when_unauthenticated(self):
        response = self.client.get("/fulfillment", follow_redirects=False)
        self.assertEqual(response.status_code, 302)

    def test_fulfillment_reserve_returns_401_when_unauthenticated(self):
        response = self.client.post("/api/fulfillment/reserve", json={})
        self.assertEqual(response.status_code, 401)

    def test_fulfillment_ship_returns_401_when_unauthenticated(self):
        response = self.client.post("/api/fulfillment/ship", json={"order_number": "x"})
        self.assertEqual(response.status_code, 401)


class AuthenticatedBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.client = eoms_app.app.test_client()
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = "admin"

    def test_dispatcher_closeout_missing_store_returns_404(self):
        response = self.client.post("/api/dispatcher/closeout", json={"store_id": "does-not-exist"})
        self.assertEqual(response.status_code, 404)

    def test_inventory_adjust_rejects_invalid_component(self):
        response = self.client.post(
            "/api/inventory/adjust",
            json={"component": "not-a-real-component", "amount": 1, "reason": "test"},
        )
        self.assertEqual(response.status_code, 400)

    def test_fulfillment_ship_missing_order_returns_404(self):
        response = self.client.post("/api/fulfillment/ship", json={"order_number": "does-not-exist"})
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
