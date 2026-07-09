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


class UploadLocalImportToAzureTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(os.environ, {
            "EOMS_BASE_URL": "https://eoms.example.test",
            "LOCAL_RMS_IMPORT_TOKEN": "shared-secret-token",
        })
        self.env_patch.start()

    def tearDown(self):
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
        with patch.dict(os.environ, {"LOCAL_RMS_IMPORT_TOKEN": ""}):
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
        mock_response.json.return_value = {"ok": True, "imported": 1}
        mock_response.raise_for_status.return_value = None

        with patch.object(eoms_local_worker.requests, "post", return_value=mock_response) as mock_post:
            result = eoms_local_worker.upload_local_import_to_azure(imported_pdfs)

        self.assertTrue(result["ok"])
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["batch_count"], 1)
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

    def test_skips_missing_pdf_files_but_still_uploads_sidecar_for_the_rest(self):
        good_pdf = self.make_pdf("BOL_111.pdf")
        imported_pdfs = {
            "111": {"pdf_path": str(good_pdf), "due_date": "", "assigned_date": ""},
            "222": {"pdf_path": str(Path(self.temp_dir.name) / "does_not_exist.pdf"), "due_date": "", "assigned_date": ""},
        }
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status.return_value = None

        with patch.object(eoms_local_worker.requests, "post", return_value=mock_response) as mock_post:
            result = eoms_local_worker.upload_local_import_to_azure(imported_pdfs)

        self.assertTrue(result["ok"])
        files = mock_post.call_args.kwargs["files"]
        pdf_field_names = [f[1][0] for f in files if f[1][0] != "bol_data.json"]
        self.assertEqual(pdf_field_names, ["BOL_111.pdf"])

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
        mock_response.json.return_value = {"ok": True, "imported": 10}
        mock_response.raise_for_status.return_value = None

        with patch.object(eoms_local_worker.requests, "post", return_value=mock_response) as mock_post:
            result = eoms_local_worker.upload_local_import_to_azure(imported_pdfs, batch_size=10)

        self.assertEqual(mock_post.call_count, 3)
        self.assertTrue(result["ok"])
        self.assertEqual(result["batch_count"], 3)
        self.assertEqual(result["imported"], 30)  # 10 + 10 + 10 reported per batch

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
        ok_response.json.return_value = {"ok": True, "imported": 1}
        ok_response.raise_for_status.return_value = None

        with patch.object(eoms_local_worker.requests, "post", side_effect=[Exception("boom"), ok_response]) as mock_post:
            result = eoms_local_worker.upload_local_import_to_azure(imported_pdfs, batch_size=1)

        self.assertEqual(mock_post.call_count, 2)
        self.assertFalse(result["ok"])  # overall failure surfaces since one batch failed
        self.assertEqual(result["batch_count"], 2)
        self.assertEqual(result["imported"], 1)  # the batch that succeeded still counted


if __name__ == "__main__":
    unittest.main()
