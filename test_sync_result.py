import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("SECRET_KEY", "sync-result-test-secret")

import app as eoms_app
import eoms_local_worker


class SyncResultTests(unittest.TestCase):
    def setUp(self):
        self.client = eoms_app.app.test_client()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temporary_directory.name) / "sync_state.json"
        self.state_patch = patch.object(eoms_app, "SYNC_STATE_FILE", self.state_path)
        self.state_patch.start()

    def tearDown(self):
        eoms_app._LOCAL_RMS_WORKER_PROCESS = None
        logging.shutdown()
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
            handler.close()
        self.state_patch.stop()
        self.temporary_directory.cleanup()

    def authenticated_post(self, path):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = "admin"
        with patch.object(eoms_app, "current_user", return_value={"username": "admin", "role": "Admin"}):
            return self.client.post(path)

    def test_post_requires_worker_bearer_token(self):
        with patch.dict(os.environ, {"EOMS_WORKER_TOKEN": "correct-token"}):
            response = self.client.post(
                "/api/sync-result",
                headers={"Authorization": "Bearer wrong-token"},
                json={"timestamp": "2026-07-08T12:00:00", "result": {}},
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["message"], "Invalid worker token.")

    def test_post_rejects_missing_worker_bearer_token(self):
        with patch.dict(os.environ, {"EOMS_WORKER_TOKEN": "correct-token", "LOCAL_RMS_IMPORT_TOKEN": ""}):
            response = self.client.post(
                "/api/sync-result",
                json={"timestamp": "2026-07-08T12:00:00", "result": {}},
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["message"], "Worker bearer token is required.")

    def test_post_persists_and_get_returns_last_result(self):
        payload = {
            "timestamp": "2026-07-08T12:00:00",
            "source": "eoms-local-worker",
            "result": {"ok": True, "status": "IMPORT COMPLETE", "imported": 3},
        }
        with patch.dict(os.environ, {"EOMS_WORKER_TOKEN": "correct-token"}):
            posted = self.client.post(
                "/api/sync-result",
                headers={"Authorization": "Bearer correct-token"},
                json=payload,
            )
        self.assertEqual(posted.status_code, 200)
        self.assertTrue(self.state_path.exists())
        self.assertFalse(self.state_path.read_bytes().startswith(b"\xef\xbb\xbf"))

        with patch.object(eoms_app, "current_user", return_value={"username": "admin", "role": "Admin"}):
            with self.client.session_transaction() as session:
                session["logged_in"] = True
                session["username"] = "admin"
            fetched = self.client.get("/api/sync-result")

        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.get_json()["sync"]["result"]["imported"], 3)

    def test_legacy_import_token_can_post_sync_result_when_worker_token_is_absent(self):
        payload = {
            "timestamp": "2026-07-08T12:00:00",
            "source": "eoms-local-worker",
            "result": {"ok": True, "status": "IMPORT COMPLETE"},
        }
        with patch.dict(os.environ, {"EOMS_WORKER_TOKEN": "", "LOCAL_RMS_IMPORT_TOKEN": "shared-token"}):
            response = self.client.post(
                "/api/sync-result",
                headers={"Authorization": "Bearer shared-token"},
                json=payload,
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_import_and_sync_result_accept_same_worker_token(self):
        with patch.dict(os.environ, {"EOMS_WORKER_TOKEN": "shared-worker-token", "LOCAL_RMS_IMPORT_TOKEN": ""}):
            sync_response = self.client.post(
                "/api/sync-result",
                headers={"Authorization": "Bearer shared-worker-token"},
                json={"timestamp": "2026-07-08T12:00:00", "result": {"ok": True}},
            )
            import_response = self.client.post(
                "/api/local-rms/import",
                headers={"Authorization": "Bearer shared-worker-token"},
            )

        self.assertEqual(sync_response.status_code, 200)
        self.assertEqual(import_response.status_code, 400)
        self.assertEqual(import_response.get_json()["message"], "Attach PDF, Excel, or CSV files as rms_file.")

    def test_local_summary_and_sidecar_are_utf8_without_bom(self):
        sidecar = Path(self.temporary_directory.name) / "bol_data.json"
        summary = eoms_local_worker.summarize_result({
            "ok": True,
            "status": "IMPORT COMPLETE",
            "found": 7,
            "imported": 2,
            "updated": 1,
            "errors": [],
        })
        eoms_local_worker.atomic_write_json(
            sidecar,
            {"last_run": "2026-07-08T12:00:00", "last_result": summary},
        )
        self.assertEqual(summary["bols_found"], 7)
        self.assertEqual(summary["bols_new"], 2)
        self.assertFalse(sidecar.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_local_worker_runs_once_writes_sidecar_and_posts_once(self):
        sidecar = Path(self.temporary_directory.name) / "bol_data.json"
        log_path = Path(self.temporary_directory.name) / "worker.log"
        with (
            patch.object(eoms_local_worker, "BOL_DATA_PATH", sidecar),
            patch.object(eoms_local_worker, "LOG_PATH", log_path),
            patch.object(eoms_local_worker, "ensure_dedicated_edge", return_value=None),
            patch.object(eoms_local_worker, "run_auto_grab", return_value={
                "ok": True,
                "status": "IMPORT COMPLETE",
                "found": 4,
                "imported": 1,
                "errors": [],
            }) as auto_grab,
            patch.object(eoms_local_worker, "post_sync_result", return_value={"ok": True}) as post_result,
            patch.object(eoms_local_worker, "close_dedicated_edge", return_value=True) as close_edge,
        ):
            exit_code = eoms_local_worker.main()
            logging.shutdown()

        self.assertEqual(exit_code, 0)
        auto_grab.assert_called_once_with()
        post_result.assert_called_once()
        close_edge.assert_called_once_with(None)
        self.assertEqual(
            json.loads(sidecar.read_text(encoding="utf-8"))["last_result"]["imported"],
            1,
        )

    def test_post_sync_result_uses_worker_token_and_logs_target_without_secret(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"ok": True}
        with (
            patch.dict(os.environ, {
                "EOMS_BASE_URL": "https://eoms.example.test/",
                "EOMS_WORKER_TOKEN": "super-secret-token",
                "LOCAL_RMS_IMPORT_TOKEN": "legacy-token",
            }),
            patch.object(eoms_local_worker.requests, "post", return_value=response) as mock_post,
            self.assertLogs(level="INFO") as logs,
        ):
            result = eoms_local_worker.post_sync_result("2026-07-08T12:00:00", {"ok": True})

        self.assertTrue(result["ok"])
        call = mock_post.call_args
        self.assertEqual(call.args[0], "https://eoms.example.test/api/sync-result")
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer super-secret-token")
        log_output = "\n".join(logs.output)
        self.assertIn("https://eoms.example.test/api/sync-result", log_output)
        self.assertIn("EOMS_WORKER_TOKEN authentication", log_output)
        self.assertNotIn("super-secret-token", log_output)

    def test_local_worker_uploads_imported_pdfs_to_azure_when_present(self):
        sidecar = Path(self.temporary_directory.name) / "bol_data.json"
        log_path = Path(self.temporary_directory.name) / "worker.log"
        with (
            patch.object(eoms_local_worker, "BOL_DATA_PATH", sidecar),
            patch.object(eoms_local_worker, "LOG_PATH", log_path),
            patch.object(eoms_local_worker, "ensure_dedicated_edge", return_value=None),
            patch.object(eoms_local_worker, "run_auto_grab", return_value={
                "ok": True,
                "status": "IMPORT COMPLETE",
                "found": 1,
                "imported": 1,
                "errors": [],
                "imported_pdfs": {"12345": {"pdf_path": "/tmp/does-not-matter.pdf", "due_date": "", "assigned_date": ""}},
            }),
            patch.object(eoms_local_worker, "upload_local_import_to_azure", return_value={"ok": True}) as upload,
            patch.object(eoms_local_worker, "post_sync_result", return_value={"ok": True}),
            patch.object(eoms_local_worker, "close_dedicated_edge", return_value=True),
        ):
            exit_code = eoms_local_worker.main()
            logging.shutdown()

        self.assertEqual(exit_code, 0)
        upload.assert_called_once_with({"12345": {"pdf_path": "/tmp/does-not-matter.pdf", "due_date": "", "assigned_date": ""}})

    def test_local_worker_skips_upload_when_no_imported_pdfs(self):
        sidecar = Path(self.temporary_directory.name) / "bol_data.json"
        log_path = Path(self.temporary_directory.name) / "worker.log"
        with (
            patch.object(eoms_local_worker, "BOL_DATA_PATH", sidecar),
            patch.object(eoms_local_worker, "LOG_PATH", log_path),
            patch.object(eoms_local_worker, "ensure_dedicated_edge", return_value=None),
            patch.object(eoms_local_worker, "run_auto_grab", return_value={
                "ok": True, "status": "IMPORT COMPLETE", "found": 0, "imported": 0, "errors": [],
            }),
            patch.object(eoms_local_worker, "upload_local_import_to_azure") as upload,
            patch.object(eoms_local_worker, "post_sync_result", return_value={"ok": True}),
            patch.object(eoms_local_worker, "close_dedicated_edge", return_value=True),
        ):
            exit_code = eoms_local_worker.main()
            logging.shutdown()

        self.assertEqual(exit_code, 0)
        upload.assert_not_called()

    def test_worker_launches_dedicated_edge_when_cdp_is_absent(self):
        process = Mock()
        process.poll.return_value = None
        edge_path = Path(self.temporary_directory.name) / "msedge.exe"
        edge_path.touch()
        profile_path = Path(self.temporary_directory.name) / "edge-profile"
        with (
            patch.object(eoms_local_worker, "EDGE_PROFILE_PATH", profile_path),
            patch.object(eoms_local_worker, "edge_executable", return_value=edge_path),
            patch.object(eoms_local_worker, "cdp_is_ready", side_effect=[False, True]),
            patch.object(eoms_local_worker.subprocess, "Popen", return_value=process) as popen,
        ):
            returned = eoms_local_worker.ensure_dedicated_edge()

        self.assertIs(returned, process)
        command = popen.call_args.args[0]
        self.assertIn("--remote-debugging-port=9223", command)
        self.assertIn(f"--user-data-dir={profile_path}", command)
        self.assertIn(eoms_local_worker.RMS_URL, command)

    def test_worker_reuses_dedicated_edge_when_cdp_is_ready(self):
        with (
            patch.object(eoms_local_worker, "cdp_is_ready", return_value=True),
            patch.object(eoms_local_worker.subprocess, "Popen") as popen,
        ):
            returned = eoms_local_worker.ensure_dedicated_edge()

        self.assertIsNone(returned)
        popen.assert_not_called()

    def test_cleanup_closes_dedicated_edge_through_cdp(self):
        browser = Mock()
        playwright = Mock()
        playwright.chromium.connect_over_cdp.return_value = browser
        manager = Mock()
        manager.__enter__ = Mock(return_value=playwright)
        manager.__exit__ = Mock(return_value=False)
        with (
            patch.object(eoms_local_worker, "cdp_is_ready", side_effect=[True, False, False]),
            patch("playwright.sync_api.sync_playwright", return_value=manager),
        ):
            closed = eoms_local_worker.close_dedicated_edge()

        self.assertTrue(closed)
        playwright.chromium.connect_over_cdp.assert_called_once_with(
            "http://127.0.0.1:9223"
        )
        browser.close.assert_called_once_with()

    def test_failure_is_synchronized_and_edge_is_closed(self):
        sidecar = Path(self.temporary_directory.name) / "bol_data.json"
        process = Mock()
        posted = {}

        def capture_result(timestamp, result):
            posted.update(result)
            return {"ok": True}

        with (
            patch.object(eoms_local_worker, "BOL_DATA_PATH", sidecar),
            patch.object(eoms_local_worker, "ensure_dedicated_edge", return_value=process),
            patch.object(eoms_local_worker, "run_auto_grab", side_effect=RuntimeError("RMS unavailable")),
            patch.object(eoms_local_worker, "post_sync_result", side_effect=capture_result),
            patch.object(eoms_local_worker, "close_dedicated_edge", return_value=True) as close_edge,
        ):
            exit_code = eoms_local_worker.main()
            logging.shutdown()

        self.assertEqual(exit_code, 1)
        self.assertFalse(posted["ok"])
        self.assertEqual(posted["error_message"], "RMS unavailable")
        close_edge.assert_called_once_with(process)

    def test_edge_cleanup_runs_when_result_post_fails(self):
        process = Mock()
        sidecar = Path(self.temporary_directory.name) / "bol_data.json"
        with (
            patch.object(eoms_local_worker, "BOL_DATA_PATH", sidecar),
            patch.object(eoms_local_worker, "ensure_dedicated_edge", return_value=process),
            patch.object(eoms_local_worker, "run_auto_grab", return_value={"ok": True}),
            patch.object(eoms_local_worker, "post_sync_result", side_effect=RuntimeError("EOMS unavailable")),
            patch.object(eoms_local_worker, "close_dedicated_edge", return_value=True) as close_edge,
        ):
            exit_code = eoms_local_worker.main()
            logging.shutdown()

        self.assertEqual(exit_code, 1)
        close_edge.assert_called_once_with(process)

    def test_launch_endpoint_uses_current_python_and_returns_immediately(self):
        process = Mock()
        process.poll.return_value = None
        with (
            patch.object(eoms_app, "IS_AZURE", False),
            patch.object(eoms_app.subprocess, "Popen", return_value=process) as popen,
        ):
            response = self.authenticated_post("/api/rms-local-worker/run")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "ok": True,
            "message": "RMS Auto Grab started.",
        })
        command = popen.call_args.args[0]
        self.assertEqual(command[0], eoms_app.sys.executable)
        self.assertTrue(command[1].endswith("eoms_local_worker.py"))

    def test_launch_endpoint_prevents_duplicate_worker(self):
        running_process = Mock()
        running_process.poll.return_value = None
        eoms_app._LOCAL_RMS_WORKER_PROCESS = running_process
        with (
            patch.object(eoms_app, "IS_AZURE", False),
            patch.object(eoms_app.subprocess, "Popen") as popen,
        ):
            response = self.authenticated_post("/api/rms-local-worker/run")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["message"], "RMS Auto Grab is already running.")
        popen.assert_not_called()

    def test_launch_endpoint_refuses_azure(self):
        with (
            patch.object(eoms_app, "IS_AZURE", True),
            patch.object(eoms_app.subprocess, "Popen") as popen,
        ):
            response = self.authenticated_post("/api/rms-local-worker/run")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["message"],
            "The local RMS worker can only be started from a local EOMS installation.",
        )
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
