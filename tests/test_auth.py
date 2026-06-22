import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "test-only-secret-key-with-at-least-32-characters")
os.environ.setdefault("SESSION_COOKIE_SECURE", "0")
os.environ.setdefault("ADMIN_PASSWORD", "test-only-admin-password")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as eoms


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        eoms.app.config.update(TESTING=True)
        self.client = eoms.app.test_client()

    def test_anonymous_pages_redirect_to_login(self):
        for path in ("/", "/dashboard", "/dispatch-map", "/driver", "/route-view/not-real"):
            response = self.client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 302, path)
            self.assertTrue(response.headers["Location"].startswith("/login"), path)

    def test_anonymous_api_returns_401(self):
        for path in ("/api/routes", "/api/dashboard-live"):
            response = self.client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 401, path)
            self.assertEqual(response.get_json()["message"], "Authentication required.")

    def test_invalid_session_is_rejected(self):
        with self.client.session_transaction() as flask_session:
            flask_session["logged_in"] = True
            flask_session["username"] = "deleted-or-fake-user"
        response = self.client.get("/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].startswith("/login"))

        with self.client.session_transaction() as flask_session:
            flask_session["logged_in"] = True
            flask_session["username"] = "deleted-or-fake-user"
        response = self.client.get("/login", follow_redirects=False)
        self.assertEqual(response.status_code, 200)

    def test_post_login_redirect_must_be_local(self):
        self.assertEqual(eoms.safe_next_url("https://attacker.example"), "/dashboard")
        self.assertEqual(eoms.safe_next_url("//attacker.example"), "/dashboard")
        self.assertEqual(eoms.safe_next_url("/dispatch-map"), "/dispatch-map")


if __name__ == "__main__":
    unittest.main()
