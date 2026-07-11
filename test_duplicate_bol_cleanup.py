import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "duplicate-bol-cleanup-test-secret")

import app as eoms_app
import routes.database_maintenance as maintenance_routes
from eoms_modules.duplicate_bol_cleanup_service import (
    backup_runtime_files,
    cleanup_safe_duplicates,
    normalize_bol_number,
    restore_backup_manifest,
    scan_duplicate_bols,
)
from eoms_modules.bol_data_audit_service import (
    bol_data_audit_report,
    normalized_status_category,
)


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


class DuplicateBolCleanupServiceTests(unittest.TestCase):
    def test_normalize_bol_number_collapses_common_formats(self):
        self.assertEqual(normalize_bol_number("BOL-12345"), "12345")
        self.assertEqual(normalize_bol_number("BOL 12345"), "12345")
        self.assertEqual(normalize_bol_number("12345"), "12345")

    def test_scan_classifies_safe_and_protected_duplicates(self):
        stores = [
            {"id": "canonical", "bol": "BOL-12345", "status": "Ready", "created_at": "2024-01-01T00:00:00"},
            {"id": "safe", "bol": "12345", "status": "Ready"},
            {"id": "route-linked", "bol": "BOL 999", "route_id": "R-1"},
            {"id": "route-copy", "bol": "999"},
        ]

        report = scan_duplicate_bols(stores, routes=[], audit_entries=[], rms_queue=[], sync_history=[])
        rows_by_id = {
            row["record"]["id"]: row
            for group in report["groups"]
            for row in group["rows"]
        }

        self.assertEqual(report["metrics"]["duplicate_groups"], 2)
        self.assertEqual(rows_by_id["safe"]["classification"], "Safe Duplicate")
        self.assertEqual(rows_by_id["route-copy"]["classification"], "Safe Duplicate")
        self.assertTrue(rows_by_id["route-linked"]["is_canonical"])

    def test_cleanup_removes_only_safe_noncanonical_records(self):
        stores = [
            {"id": "keep-route", "bol": "BOL-123", "route_id": "R-1"},
            {"id": "remove-safe", "bol": "123"},
            {"id": "keep-recovery", "bol": "BOL-777", "corner_posts": 2},
            {"id": "keep-canonical", "bol": "777"},
        ]

        kept, removed, _ = cleanup_safe_duplicates(stores, routes=[], audit_entries=[], rms_queue=[], sync_history=[])

        self.assertEqual({item["id"] for item in removed}, {"remove-safe", "keep-canonical"})
        self.assertEqual({item["id"] for item in kept}, {"keep-route", "keep-recovery"})

    def test_backup_and_restore_manifest_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stores_file = root / "stores.json"
            routes_file = root / "routes.json"
            write_json(stores_file, [{"id": "before", "bol": "BOL-1"}])
            write_json(routes_file, [])
            files = {"stores": stores_file, "routes": routes_file}

            manifest = backup_runtime_files(files, root / "backups")
            write_json(stores_file, [{"id": "after", "bol": "BOL-2"}])
            manifest["manifest_path"] = str(Path(manifest["path"]) / "manifest.json")
            restore_backup_manifest(manifest, files)

            self.assertEqual(json.loads(stores_file.read_text(encoding="utf-8"))[0]["id"], "before")


class BolDataAuditServiceTests(unittest.TestCase):
    def test_status_normalization_is_conservative(self):
        self.assertEqual(normalized_status_category({"status": "Unassigned"}), "Active")
        self.assertEqual(normalized_status_category({"status": "Completed"}), "Completed")
        self.assertEqual(normalized_status_category({"status": "Recovered"}), "Recovered")
        self.assertEqual(normalized_status_category({"receiving_status": "Received"}), "Received")
        self.assertEqual(normalized_status_category({"status": "Archived"}), "Archived/Inactive")
        self.assertEqual(normalized_status_category({"status": "Mystery"}), "Uncertain")

    def test_audit_report_age_missing_fields_and_test_demo_detection(self):
        stores = [
            {
                "id": "active",
                "bol": "BOL-123",
                "status": "Unassigned",
                "created_at": "2026-06-01T00:00:00",
                "updated_at": "2026-06-02T00:00:00",
                "rms_url": "https://rms.example/123",
                "rms_status": "Open in RMS",
            },
            {
                "id": "old-demo",
                "bol": "",
                "status": "",
                "store_name": "Demo Store",
                "created_at": "2026-01-01T00:00:00",
            },
        ]

        report = bol_data_audit_report(stores, routes=[], now=__import__("datetime").datetime(2026, 7, 11, 12, 0, 0))
        demo_row = next(row for row in report["records"] if row["record_id"] == "old-demo")

        self.assertEqual(report["metrics"]["total_bol_records"], 2)
        self.assertEqual(report["metrics"]["active_records"], 1)
        self.assertEqual(report["metrics"]["missing_status_records"], 1)
        self.assertEqual(report["metrics"]["older_than_180_days"], 1)
        self.assertEqual(report["metrics"]["missing_or_invalid_bol_records"], 1)
        self.assertEqual(report["metrics"]["test_demo_sample_records"], 1)
        self.assertEqual(report["metrics"]["open_in_rms_records"], 1)
        self.assertIn("missing_or_invalid_bol", demo_row["audit_flags"])
        self.assertIn("test_demo_sample", demo_row["audit_flags"])


class DuplicateBolCleanupRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = eoms_app.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.files = {
            "STORES_FILE": self.root / "stores.json",
            "ROUTES_FILE": self.root / "routes.json",
            "RMS_QUEUE_FILE": self.root / "rms_queue.json",
            "SYNC_HISTORY_FILE": self.root / "sync_history.json",
            "AUDIT_FILE": self.root / "audit_log.json",
        }
        write_json(self.files["STORES_FILE"], [
            {"id": "keep", "bol": "BOL-12345", "created_at": "2024-01-01T00:00:00"},
            {"id": "remove", "bol": "12345"},
        ])
        write_json(self.files["ROUTES_FILE"], [])
        write_json(self.files["RMS_QUEUE_FILE"], [])
        write_json(self.files["SYNC_HISTORY_FILE"], [])
        write_json(self.files["AUDIT_FILE"], [])

        self.patchers = [
            patch.object(maintenance_routes, "BASE_DIR", self.root),
            patch.object(maintenance_routes, "STORES_FILE", self.files["STORES_FILE"]),
            patch.object(maintenance_routes, "ROUTES_FILE", self.files["ROUTES_FILE"]),
            patch.object(maintenance_routes, "RMS_QUEUE_FILE", self.files["RMS_QUEUE_FILE"]),
            patch.object(maintenance_routes, "SYNC_HISTORY_FILE", self.files["SYNC_HISTORY_FILE"]),
            patch.object(maintenance_routes, "AUDIT_FILE", self.files["AUDIT_FILE"]),
            patch.object(maintenance_routes, "audit", lambda action, details: None),
        ]
        for patcher in self.patchers:
            patcher.start()

        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = "admin"

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.tmp.cleanup()

    def test_duplicate_bol_routes_are_registered(self):
        rules = {r.rule for r in eoms_app.app.url_map.iter_rules()}
        expected = {
            "/admin/duplicate-bols",
            "/admin/bol-data-audit",
            "/api/admin/duplicate-bols/scan",
            "/api/admin/duplicate-bols/cleanup",
            "/api/admin/duplicate-bols/rollback",
            "/api/admin/duplicate-bols/report",
            "/api/admin/bol-data-audit/scan",
            "/api/admin/bol-data-audit/report",
        }
        self.assertTrue(expected.issubset(rules))

    def test_bol_data_audit_page_requires_admin_login(self):
        client = eoms_app.app.test_client()
        response = client.get("/admin/bol-data-audit", follow_redirects=False)
        self.assertIn(response.status_code, (302, 401))

    def test_duplicate_bol_page_renders_scan_button_and_script_wiring(self):
        response = self.client.get("/admin/duplicate-bols")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="scanDuplicateBolsBtn"', html)
        self.assertIn('document.getElementById("scanDuplicateBolsBtn")', html)
        self.assertIn('console.log("Duplicate BOL Cleanup JavaScript loaded")', html)
        self.assertIn('console.log("Scan button clicked")', html)
        self.assertIn('fetch("/api/admin/duplicate-bols/scan"', html)
        self.assertIn('setStatus("Scanning duplicate BOL records...")', html)

    def test_bol_data_audit_page_renders_scan_button_and_script_wiring(self):
        response = self.client.get("/admin/bol-data-audit")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="bolAuditScanBtn"', html)
        self.assertIn('document.getElementById("bolAuditScanBtn")', html)
        self.assertIn('console.log("Production BOL Data Audit JavaScript loaded")', html)
        self.assertIn('fetch("/api/admin/bol-data-audit/scan"', html)
        self.assertIn('Scanning production BOL records...', html)
        self.assertIn('/api/admin/bol-data-audit/report', html)

    def test_scan_is_read_only(self):
        before = self.files["STORES_FILE"].read_text(encoding="utf-8")
        response = self.client.post("/api/admin/duplicate-bols/scan")
        after = self.files["STORES_FILE"].read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(before, after)
        self.assertEqual(response.get_json()["metrics"]["safe_duplicates"], 1)

    def test_bol_data_audit_scan_is_read_only(self):
        before = self.files["STORES_FILE"].read_text(encoding="utf-8")
        response = self.client.post("/api/admin/bol-data-audit/scan")
        after = self.files["STORES_FILE"].read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(before, after)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["metrics"]["total_bol_records"], 2)
        self.assertIn("status_breakdown", payload)
        self.assertIn("records", payload)

    def test_bol_data_audit_report_endpoint_downloads_json(self):
        response = self.client.get("/api/admin/bol-data-audit/report")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        self.assertIn("production-bol-data-audit-report.json", response.headers.get("Content-Disposition", ""))
        self.assertTrue(response.get_json()["ok"])

    def test_cleanup_creates_backup_and_removes_only_safe_duplicate(self):
        response = self.client.post("/api/admin/duplicate-bols/cleanup")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        stores = json.loads(self.files["STORES_FILE"].read_text(encoding="utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["removed_count"], 1)
        self.assertEqual([item["id"] for item in stores], ["keep"])
        self.assertTrue(any((self.root / "backups").glob("duplicate_bol_cleanup_*/manifest.json")))

    def test_cleanup_does_not_write_when_backup_fails(self):
        with patch.object(maintenance_routes, "backup_runtime_files", side_effect=RuntimeError("backup failed")):
            response = self.client.post("/api/admin/duplicate-bols/cleanup")

        stores = json.loads(self.files["STORES_FILE"].read_text(encoding="utf-8"))
        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual({item["id"] for item in stores}, {"keep", "remove"})

    def test_rollback_requires_confirmation_and_restores_latest_backup(self):
        cleanup_response = self.client.post("/api/admin/duplicate-bols/cleanup")
        self.assertEqual(cleanup_response.status_code, 200)

        rejected = self.client.post("/api/admin/duplicate-bols/rollback", json={"confirmation": "rollback"})
        self.assertEqual(rejected.status_code, 400)

        accepted = self.client.post("/api/admin/duplicate-bols/rollback", json={"confirmation": "ROLLBACK"})
        stores = json.loads(self.files["STORES_FILE"].read_text(encoding="utf-8"))

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual({item["id"] for item in stores}, {"keep", "remove"})


if __name__ == "__main__":
    unittest.main()
