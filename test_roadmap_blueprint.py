"""FT6: proves the Roadmap blueprint extraction did not change externally
visible behavior versus the old inline app.py route."""

import os
import unittest

os.environ.setdefault("SECRET_KEY", "roadmap-blueprint-test-secret")

import app as eoms_app


class RoadmapBlueprintTests(unittest.TestCase):
    def setUp(self):
        self.client = eoms_app.app.test_client()

    def test_roadmap_route_is_registered(self):
        rules = {r.rule for r in eoms_app.app.url_map.iter_rules()}
        self.assertIn("/roadmap", rules)

    def test_roadmap_redirects_to_login_when_unauthenticated(self):
        response = self.client.get("/roadmap", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))

    def test_roadmap_renders_when_authenticated(self):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = "admin"
        response = self.client.get("/roadmap")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
