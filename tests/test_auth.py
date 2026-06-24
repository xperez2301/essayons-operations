import os
import sys
import tempfile
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

    def test_playwright_dependency_error_is_repairable(self):
        message = "Host system is missing dependencies to run browsers. Please install them with playwright install-deps"
        self.assertTrue(eoms.is_missing_browser_deps(message))
        self.assertFalse(eoms.is_missing_browser_binary(message))

    def test_playwright_missing_browser_error_is_repairable(self):
        message = "Executable doesn't exist at /home/playwright/chromium. Please run playwright install"
        self.assertTrue(eoms.is_missing_browser_binary(message))
        self.assertFalse(eoms.is_missing_browser_deps(message))

    def test_printable_bol_saves_as_pdf_when_browser_supports_pdf(self):
        class FakePage:
            def emulate_media(self, media):
                self.media = media

            def pdf(self, path, **kwargs):
                Path(path).write_bytes(b"%PDF-1.4\n% test\n")

        original_bol_dir = eoms.BOL_DIR
        try:
            with tempfile.TemporaryDirectory() as tmp:
                eoms.BOL_DIR = Path(tmp)
                path = eoms.save_printable_pdf(
                    FakePage(),
                    {"bol": "950225", "origin": "Test", "store_name": "Store", "city": "San Antonio", "state": "TX", "status": "Unassigned"},
                    "<html></html>",
                )
                self.assertTrue(path.endswith(".pdf"))
                self.assertTrue(Path(path).exists())
        finally:
            eoms.BOL_DIR = original_bol_dir

    def test_rms_login_page_detector_matches_login_screen(self):
        class FakeLocator:
            def inner_text(self, timeout=0):
                return "Sign In Username Password Forgot your password?"

        class FakePage:
            url = "https://rms.reusability.com/login"

            def title(self):
                return "RMS - LoginPage"

            def locator(self, selector):
                return FakeLocator()

        self.assertTrue(eoms.is_rms_login_page(FakePage()))

    def test_rms_wait_page_detector_matches_transformation_shell(self):
        html = "<html><head><title>Transformation</title></head><body>Please wait...</body></html>"
        self.assertTrue(eoms.is_rms_wait_page("Please wait...", html))
        self.assertFalse(eoms.is_rms_wait_page("Bill of Lading 950225\nOrigin HOUSTON", ""))

    def test_missing_rms_bols_are_archived_without_deleting_store(self):
        original_stores_file = eoms.STORES_FILE
        original_bol_dir = eoms.BOL_DIR
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                eoms.BOL_DIR = root / "bol_files"
                eoms.STORES_FILE = root / "stores.json"
                pdf = eoms.BOL_DIR / "Imported" / "2026" / "06_June" / "BOL_950225.pdf"
                pdf.parent.mkdir(parents=True, exist_ok=True)
                pdf.write_bytes(b"%PDF-1.4\n")
                eoms.STORES_FILE.write_text(
                    '[{"id":"s1","bol":"950225","status":"Unassigned","pdf_path":"%s"}]' % str(pdf).replace("\\", "\\\\"),
                    encoding="utf-8",
                )

                result = eoms.mark_stores_missing_from_rms({"111111"})
                stores = eoms.read_json(eoms.STORES_FILE)

                self.assertEqual(result["rms_missing"], 1)
                self.assertEqual(stores[0]["rms_status"], "Missing from RMS")
                self.assertEqual(stores[0]["closed_source"], "RMS")
                self.assertTrue(stores[0]["pdf_path"].endswith(".pdf"))
                self.assertIn("RMS_Closed", stores[0]["pdf_path"])
                self.assertTrue(Path(stores[0]["pdf_path"]).exists())
                self.assertEqual(eoms.active_map_stores(stores), [])
        finally:
            eoms.STORES_FILE = original_stores_file
            eoms.BOL_DIR = original_bol_dir


if __name__ == "__main__":
    unittest.main()
