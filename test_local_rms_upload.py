"""FT6: covers eoms_local_worker.upload_local_import_to_azure() - the piece
that actually gets scraped BOL data onto the live Azure site.

Context: RMS blocks connections from Azure's own servers (confirmed via a
live 403 during testing), so the RMS scrape can only ever run on a local
machine. eoms_local_worker.py already posted a status SUMMARY to Azure's
/api/sync-result, but that's just counts for the dashboard - it never
carried the actual new BOL records. This uploads the PDFs the local scrape
just saved to Azure's /api/local-rms/import (the same endpoint manual PDF
imports use), which is the only way the real data reaches the live site.

No live network access here (this environment can't reach the real Azure
site or RMS) - requests.post is mocked throughout.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("SECRET_KEY", "local-rms-upload-test-secret")

import eoms_local_worker
import app as eoms_app


class FakeUpload:
    def __init__(self, filename, content=b"%PDF-fake"):
        self.filename = filename
        self.content = content

    def save(self, path):
        Path(path).write_bytes(self.content)


class UploadLocalImportToAzureTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(os.environ, {
            "EOMS_BASE_URL": "https://eoms.example.test",
            "EOMS_WORKER_TOKEN": "",
            "LOCAL_RMS_IMPORT_TOKEN": "shared-secret-token",
            "EOMS_LOCAL_SYNC_QUEUE_FILE": str(Path(self.temp_dir.name) / "sync_queue.json"),
            "EOMS_LOCAL_SYNC_HISTORY_FILE": str(Path(self.temp_dir.name) / "sync_history.json"),
        })
        self.env_patch.start()
        self.path_patches = [
            patch.object(eoms_local_worker, "SYNC_QUEUE_PATH", Path(os.environ["EOMS_LOCAL_SYNC_QUEUE_FILE"])),
            patch.object(eoms_local_worker, "SYNC_HISTORY_PATH", Path(os.environ["EOMS_LOCAL_SYNC_HISTORY_FILE"])),
        ]
        for item in self.path_patches:
            item.start()

    def tearDown(self):
        for item in self.path_patches:
            item.stop()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def make_pdf(self, name="BOL_12345.pdf", content=b"%PDF-fake"):
        path = Path(self.temp_dir.name) / name
        path.write_bytes(content)
        return path

    def test_no_imported_pdfs_is_a_no_op(self):
        with patch.object(eoms_local_worker.requests, "post") as mock_post:
            result = eoms_local_worker.upload_local_import_to_azure({})
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("skipped"))
        mock_post.assert_not_called()

    def test_missing_token_raises(self):
        with patch.dict(os.environ, {"EOMS_WORKER_TOKEN": "", "LOCAL_RMS_IMPORT_TOKEN": ""}):
            with self.assertRaises(RuntimeError):
                eoms_local_worker.upload_local_import_to_azure({
                    "12345": {"pdf_path": str(self.make_pdf()), "due_date": "", "assigned_date": ""}
                })

    def test_missing_base_url_raises(self):
        with patch.dict(os.environ, {"EOMS_BASE_URL": "", "AZURE_EOMS_URL": ""}):
            with self.assertRaises(RuntimeError):
                eoms_local_worker.upload_local_import_to_azure({
                    "12345": {"pdf_path": str(self.make_pdf()), "due_date": "", "assigned_date": ""}
                })

    def test_uploads_pdf_and_bol_data_sidecar_with_bearer_token(self):
        pdf_path = self.make_pdf()
        imported_pdfs = {
            "12345": {"pdf_path": str(pdf_path), "due_date": "07/15/2026", "assigned_date": "07/09/2026"},
        }
        mock_response = MagicMock()
        # Real server response shape from import_rms_uploaded_files(): added/
        # duplicates/need_review, not imported/updated.
        mock_response.json.return_value = {
            "ok": True,
            "added": 1,
            "duplicates": 0,
            "need_review": 0,
            "added_bols": [{"bol": "12345", "normalized_bol": "12345"}],
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(eoms_local_worker.requests, "post", return_value=mock_response) as mock_post:
            result = eoms_local_worker.upload_local_import_to_azure(imported_pdfs)

        self.assertTrue(result["ok"])
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["imported"], 1)  # backward-compat alias
        self.assertEqual(result["batch_count"], 1)
        self.assertEqual(result["confirmed_bols"], ["12345"])
        self.assertFalse(pdf_path.exists())
        mock_post.assert_called_once()
        call = mock_post.call_args
        self.assertEqual(call.args[0], "https://eoms.example.test/api/local-rms/import")
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer shared-secret-token")

        files = call.kwargs["files"]
        field_names = [f[0] for f in files]
        self.assertEqual(field_names.count("rms_file"), 2)  # the PDF + the bol_data.json sidecar

        sidecar_entry = next(f for f in files if f[1][0] == "bol_data.json")
        sidecar_payload = json.loads(sidecar_entry[1][1])
        self.assertEqual(sidecar_payload["12345"]["due_date"], "07/15/2026")

    def test_upload_prefers_eoms_worker_token_when_configured(self):
        pdf_path = self.make_pdf("BOL_worker_token.pdf")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ok": True,
            "added": 1,
            "duplicates": 0,
            "need_review": 0,
            "added_bols": [{"bol": "555", "normalized_bol": "555"}],
        }
        mock_response.raise_for_status.return_value = None

        with (
            patch.dict(os.environ, {"EOMS_WORKER_TOKEN": "worker-token", "LOCAL_RMS_IMPORT_TOKEN": "legacy-token"}),
            patch.object(eoms_local_worker.requests, "post", return_value=mock_response) as mock_post,
        ):
            result = eoms_local_worker.upload_local_import_to_azure({
                "555": {"pdf_path": str(pdf_path), "due_date": "", "assigned_date": ""}
            })

        self.assertTrue(result["ok"])
        self.assertEqual(mock_post.call_args.kwargs["headers"]["Authorization"], "Bearer worker-token")

    def test_deletes_local_pdf_when_azure_confirms_duplicate_exists(self):
        pdf_path = self.make_pdf("BOL_duplicate.pdf")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ok": True,
            "added": 0,
            "duplicates": 1,
            "need_review": 0,
            "duplicate_bols": [{"bol": "BOL 12345", "normalized_bol": "12345"}],
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(eoms_local_worker.requests, "post", return_value=mock_response):
            result = eoms_local_worker.upload_local_import_to_azure({
                "BOL 12345": {"pdf_path": str(pdf_path), "due_date": "", "assigned_date": ""}
            })

        self.assertTrue(result["ok"])
        self.assertEqual(result["duplicates"], 1)
        self.assertFalse(pdf_path.exists())
        self.assertEqual(result["retained_for_retry"], {})

    def test_retains_unconfirmed_pdf_for_retry_with_reason(self):
        pdf_path = self.make_pdf("BOL_unconfirmed.pdf")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ok": False,
            "added": 0,
            "duplicates": 0,
            "failed_bols": [{"bol": "999", "normalized_bol": "999", "reason": "parse failed"}],
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(eoms_local_worker.requests, "post", return_value=mock_response):
            result = eoms_local_worker.upload_local_import_to_azure({
                "999": {"pdf_path": str(pdf_path), "due_date": "", "assigned_date": ""}
            })

        self.assertFalse(result["ok"])
        self.assertTrue(pdf_path.exists())
        self.assertIn("999", result["retained_for_retry"])
        self.assertIn("failure_reason", result["retained_for_retry"]["999"])

    def test_skips_missing_pdf_files_but_still_uploads_sidecar_for_the_rest(self):
        good_pdf = self.make_pdf("BOL_111.pdf")
        imported_pdfs = {
            "111": {"pdf_path": str(good_pdf), "due_date": "", "assigned_date": ""},
            "222": {"pdf_path": str(Path(self.temp_dir.name) / "does_not_exist.pdf"), "due_date": "", "assigned_date": ""},
        }
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ok": True,
            "added": 1,
            "duplicates": 0,
            "added_bols": [{"bol": "111", "normalized_bol": "111"}],
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(eoms_local_worker.requests, "post", return_value=mock_response) as mock_post:
            result = eoms_local_worker.upload_local_import_to_azure(imported_pdfs)

        self.assertFalse(result["ok"])
        files = mock_post.call_args.kwargs["files"]
        pdf_field_names = [f[1][0] for f in files if f[1][0] != "bol_data.json"]
        self.assertEqual(pdf_field_names, ["BOL_111.pdf"])
        self.assertFalse(good_pdf.exists())
        self.assertIn("222", result["retained_for_retry"])

    def test_all_pdfs_missing_returns_failure_without_posting(self):
        imported_pdfs = {
            "111": {"pdf_path": str(Path(self.temp_dir.name) / "gone.pdf"), "due_date": "", "assigned_date": ""},
        }
        with patch.object(eoms_local_worker.requests, "post") as mock_post:
            result = eoms_local_worker.upload_local_import_to_azure(imported_pdfs)
        self.assertFalse(result["ok"])
        mock_post.assert_not_called()

    def test_splits_large_imports_into_multiple_batches(self):
        # 25 BOLs with batch_size=10 should mean 3 separate requests to Azure,
        # not one giant request that risks a platform-level 502 timeout.
        imported_pdfs = {}
        for i in range(25):
            pdf_path = self.make_pdf(f"BOL_{i}.pdf")
            imported_pdfs[str(i)] = {"pdf_path": str(pdf_path), "due_date": "", "assigned_date": ""}

        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "added": 10, "duplicates": 0, "need_review": 0}
        mock_response.raise_for_status.return_value = None

        with patch.object(eoms_local_worker.requests, "post", return_value=mock_response) as mock_post:
            result = eoms_local_worker.upload_local_import_to_azure(imported_pdfs, batch_size=10)

        self.assertEqual(mock_post.call_count, 3)
        self.assertTrue(result["ok"])
        self.assertEqual(result["batch_count"], 3)
        self.assertEqual(result["added"], 30)  # 10 + 10 + 10 reported per batch
        self.assertEqual(result["imported"], 30)  # backward-compat alias

        for call in mock_post.call_args_list:
            files = call.kwargs["files"]
            pdf_count = sum(1 for f in files if f[1][0] != "bol_data.json")
            self.assertLessEqual(pdf_count, 10)

    def test_one_failed_batch_does_not_block_the_others(self):
        good_pdf_1 = self.make_pdf("BOL_1.pdf")
        good_pdf_2 = self.make_pdf("BOL_2.pdf")
        imported_pdfs = {
            "1": {"pdf_path": str(good_pdf_1), "due_date": "", "assigned_date": ""},
            "2": {"pdf_path": str(good_pdf_2), "due_date": "", "assigned_date": ""},
        }
        ok_response = MagicMock()
        ok_response.json.return_value = {"ok": True, "added": 1, "duplicates": 0, "need_review": 0}
        ok_response.raise_for_status.return_value = None

        with patch.object(eoms_local_worker.requests, "post", side_effect=[Exception("boom"), ok_response]) as mock_post:
            result = eoms_local_worker.upload_local_import_to_azure(imported_pdfs, batch_size=1)

        self.assertEqual(mock_post.call_count, 2)
        self.assertFalse(result["ok"])  # overall failure surfaces since one batch failed
        self.assertEqual(result["batch_count"], 2)
        self.assertEqual(result["added"], 1)  # the batch that succeeded still counted

    def test_unconfirmed_success_response_remains_in_persistent_queue_for_retry(self):
        pdf_path = self.make_pdf("BOL_unconfirmed_ok.pdf")
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "added": 0, "duplicates": 0}
        mock_response.raise_for_status.return_value = None

        with patch.object(eoms_local_worker.requests, "post", return_value=mock_response):
            result = eoms_local_worker.upload_local_import_to_azure({
                "777": {"pdf_path": str(pdf_path), "due_date": "", "assigned_date": ""}
            })

        self.assertFalse(result["ok"])
        self.assertTrue(pdf_path.exists())
        self.assertEqual(result["active_queue_count"], 1)
        queue = json.loads(Path(os.environ["EOMS_LOCAL_SYNC_QUEUE_FILE"]).read_text(encoding="utf-8"))
        self.assertEqual(queue["777"]["status"], "Failed")

    def test_confirmed_history_prevents_reupload_after_worker_restart(self):
        pdf_path = self.make_pdf("BOL_history.pdf")
        history_path = Path(os.environ["EOMS_LOCAL_SYNC_HISTORY_FILE"])
        history_path.write_text(json.dumps([{
            "run_id": "old",
            "bols": [{"bol": "888", "normalized_bol": "888", "status": "Imported"}],
        }]), encoding="utf-8")

        with patch.object(eoms_local_worker.requests, "post") as mock_post:
            result = eoms_local_worker.upload_local_import_to_azure({
                "BOL-888": {"pdf_path": str(pdf_path), "due_date": "", "assigned_date": ""}
            })

        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertFalse(json.loads(Path(os.environ["EOMS_LOCAL_SYNC_QUEUE_FILE"]).read_text(encoding="utf-8")))
        mock_post.assert_not_called()


class LocalRmsImportDuplicateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.stores_path = self.root / "stores.json"
        self.routes_path = self.root / "routes.json"
        self.audit_path = self.root / "audit.json"
        self.queue_path = self.root / "rms_queue.json"
        self.upload_dir = self.root / "uploads"
        self.bol_dir = self.root / "bol_files"
        self.upload_dir.mkdir()
        self.bol_dir.mkdir()
        self.stores_path.write_text(json.dumps([
            {"id": "existing", "bol": "BOL-12345", "origin": "Austin", "status": "Unassigned"}
        ]), encoding="utf-8")
        self.audit_path.write_text("[]", encoding="utf-8")
        self.queue_path.write_text(json.dumps([
            {"bol": "12345", "queue_status": "New"}
        ]), encoding="utf-8")

        self.patches = [
            patch.object(eoms_app, "STORES_FILE", self.stores_path),
            patch.object(eoms_app, "ROUTES_FILE", self.routes_path),
            patch.object(eoms_app, "AUDIT_FILE", self.audit_path),
            patch.object(eoms_app, "RMS_QUEUE_FILE", self.queue_path),
            patch.object(eoms_app, "UPLOAD_DIR", self.upload_dir),
            patch.object(eoms_app, "BOL_DIR", self.bol_dir),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.temp_dir.cleanup()

    def test_duplicate_pdf_is_reported_and_not_retained_in_bol_storage(self):
        parsed_duplicate = {
            "id": "new",
            "bol": "12345",
            "origin": "Austin",
            "store_name": "Duplicate Store",
            "city": "Austin",
            "state": "TX",
            "status": "Unassigned",
        }
        with patch.object(eoms_app, "parse_rms_pdf", return_value=parsed_duplicate):
            result = eoms_app.import_rms_uploaded_files(
                [FakeUpload("BOL_12345.pdf")],
                source="Local RMS Import",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["added"], 0)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["duplicate_bols"][0]["normalized_bol"], "12345")
        self.assertEqual(result["queue_confirmed"], 1)
        self.assertEqual(json.loads(self.stores_path.read_text(encoding="utf-8"))[0]["bol"], "BOL-12345")
        self.assertEqual(json.loads(self.queue_path.read_text(encoding="utf-8"))[0]["queue_status"], "Imported")
        self.assertEqual(list(self.bol_dir.rglob("*.pdf")), [])


if __name__ == "__main__":
    unittest.main()
