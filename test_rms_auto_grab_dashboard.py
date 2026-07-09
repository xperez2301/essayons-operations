"""FT6: covers /api/rms/auto-grab-bols - the Azure-side handler for the
Automation Center's "Run RMS Auto Grab" button. Unlike /api/rms-local-worker/run
(which spawns a local subprocess and safely refuses on Azure), this endpoint
runs the RMS import synchronously in-process using headless Chromium, so it's
the path that actually lets Auto Grab work from the hosted website.

These tests mock rms_full_import_with_playwright itself (never touch a real
browser or the real RMS portal - that's infeasible in CI/this environment) and
focus on the two things that matter operationally:
  1. This endpoint now requires admin (previously any logged-in user could
     trigger a full RMS scrape hitting the external portal with the saved
     credentials - a real access-control gap, tightened here to match the
     /automation-center page's own admin-only access).
  2. The result gets written to SYNC_STATE_FILE in the same normalized shape
     (bols_found/stores_checked/error_message/etc.) that the local worker's
     /api/sync-result POST uses, so the dashboard cards show consistent data
     regardless of which path produced the run.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "rms-auto-grab-dashboard-test-secret")

import app as eoms_app


class RmsAutoGrabDashboardTests(unittest.TestCase):
    def setUp(self):
        self.client = eoms_app.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sync_state_path = Path(self.temp_dir.name) / "sync_state.json"
        self.sync_history_path = Path(self.temp_dir.name) / "sync_history.json"
        self.sync_history_path.write_text("[]", encoding="utf-8")

        self.patches = [
            patch.object(eoms_app, "SYNC_STATE_FILE", self.sync_state_path),
            patch.object(eoms_app, "SYNC_HISTORY_FILE", self.sync_history_path),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp_dir.cleanup()

    def login_as(self, username, role):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = username
        user = {"username": username, "display_name": username, "role": role, "active": True, "assigned_cities": ["All"]}
        return patch.object(eoms_app, "current_user", return_value=user)

    def test_non_admin_is_rejected(self):
        with self.login_as("dispatcher1", "Dispatcher"):
            with patch.object(eoms_app, "rms_full_import_with_playwright") as mock_import:
                response = self.client.post("/api/rms/auto-grab-bols", json={})
        self.assertEqual(response.status_code, 403)
        mock_import.assert_not_called()

    def test_admin_success_writes_normalized_sync_state(self):
        fake_result = {
            "ok": True,
            "status": "IMPORT COMPLETE",
            "message": "Scanned 5 BOLs. Imported 2. Updated 1.",
            "bol_count": 5,
            "found": 5,
            "imported": 2,
            "updated": 1,
            "skipped": 2,
            "need_review": 0,
            "errors": [],
        }
        with self.login_as("admin1", "Admin"):
            with patch.object(eoms_app, "rms_full_import_with_playwright", return_value=dict(fake_result)) as mock_import:
                response = self.client.post("/api/rms/auto-grab-bols", json={})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        # The raw (unsummarized) result still comes back in the HTTP response.
        self.assertEqual(payload["result"]["imported"], 2)
        mock_import.assert_called_once()

        state = json.loads(self.sync_state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["source"], "azure-dashboard-auto-grab")
        summarized = state["result"]
        self.assertTrue(summarized["ok"])
        self.assertEqual(summarized["bols_found"], 5)
        self.assertEqual(summarized["bols_new"], 2)
        self.assertEqual(summarized["imported"], 2)
        self.assertEqual(summarized["updated"], 1)
        self.assertEqual(summarized["error_message"], "")

    def test_failed_run_sets_error_message_in_sync_state(self):
        fake_result = {
            "ok": False,
            "status": "AUTO GRAB ERROR",
            "message": "RMS Auto Grab failed before import completed: boom",
            "found": 0,
            "imported": 0,
            "updated": 0,
            "failed": 1,
        }
        with self.login_as("admin1", "Admin"):
            with patch.object(eoms_app, "rms_full_import_with_playwright", return_value=dict(fake_result)):
                response = self.client.post("/api/rms/auto-grab-bols", json={})

        payload = response.get_json()
        self.assertFalse(payload["ok"])

        state = json.loads(self.sync_state_path.read_text(encoding="utf-8"))
        summarized = state["result"]
        self.assertFalse(summarized["ok"])
        self.assertIn("boom", summarized["error_message"])

    def test_routes_registered(self):
        rules = {r.rule for r in eoms_app.app.url_map.iter_rules()}
        self.assertIn("/api/rms/auto-grab-bols", rules)
        self.assertIn("/automation-center", rules)


if __name__ == "__main__":
    unittest.main()
