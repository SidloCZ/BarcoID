"""
Resilience and recovery tests for BOLD sequence validation, HTTP 400 recovery,
NCBI QBLAST HTML rate-limit protection, and skip-ncbi pipeline execution.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from barcoid.cache import CacheManager
from barcoid.config import BarcoIDConfig
from barcoid.engines.blast_remote import RemoteBlastEngine
from barcoid.engines.bold import BoldEngine
from barcoid.pipeline import BarcoIDPipeline


class TestBoldAndRemoteResilience(unittest.TestCase):
    """Verifies error handling and isolation across external engines."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)
        self.cache_dir = self.work_dir / ".id_cache"
        self.cache_manager = CacheManager(self.cache_dir)
        self.config = BarcoIDConfig(cache_dir=self.cache_dir, output_dir=self.work_dir / "results")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_bold_sequence_quality_screening(self):
        engine = BoldEngine(self.config, self.cache_manager)

        # 1. Valid sequence
        valid_seq = "ACGT" * 15  # 60 bp, 100% ACGT
        is_val, reason = engine._validate_sequence_quality(valid_seq)
        self.assertTrue(is_val)
        self.assertEqual(reason, "")

        # 2. Too short (<20 bp)
        short_seq = "ACGTACGT"  # 8 bp
        is_val, reason = engine._validate_sequence_quality(short_seq)
        self.assertFalse(is_val)
        self.assertIn("below BOLD minimum", reason)

        # 3. Too many ambiguous / N bases (<75% ACGT-)
        ambig_seq = "NNNNNNNNNNNNNNNNNNN" + "ACGT" * 2  # 19 Ns + 8 ACGT = 27 bp, 29.6% ACGT
        is_val, reason = engine._validate_sequence_quality(ambig_seq)
        self.assertFalse(is_val)
        self.assertIn("Valid nucleotide ratio", reason)

    @patch("requests.post")
    def test_bold_http_400_isolates_bad_sequence(self, mock_post):
        """Verifies that an HTTP 400 with a label error isolates the bad sequence without dropping valid ones."""
        engine = BoldEngine(self.config, self.cache_manager)

        # First call fails with 400 for 'bad_label'
        mock_resp_fail = MagicMock()
        mock_resp_fail.status_code = 400
        mock_resp_fail.text = '{"detail":"Invalid sequence for label \'bad_label\': valid nucleotide count is too low"}'

        # Second call succeeds for remaining sequences
        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.json.return_value = {"sub_id": "SUB123"}

        mock_post.side_effect = [mock_resp_fail, mock_resp_ok]

        with patch.object(engine, "_poll_results") as mock_poll:
            mock_poll.return_value = {
                "good_label": {
                    "has_match": True,
                    "top_genus": "Camponotus",
                    "top_species": "Camponotus ligniperda",
                    "top_pct_identity": 99.0,
                    "all_hits": [],
                }
            }

            sequences = [
                ("bad_label", "ACGT" * 10),
                ("good_label", "ACGT" * 10),
            ]
            results = engine.identify_sequences(sequences)

            self.assertIn("bad_label", results)
            self.assertIn("good_label", results)
            self.assertFalse(results["bad_label"]["has_match"])
            self.assertIn("Rejected by BOLD API", results["bad_label"]["qc_note"])
            self.assertTrue(results["good_label"]["has_match"])
            self.assertEqual(results["good_label"]["top_genus"], "Camponotus")

    @patch("time.sleep")
    @patch("requests.post")
    def test_ncbi_remote_html_error_does_not_poison_cache(self, mock_post, mock_sleep):
        """Verifies that an HTML rate limit response from NCBI does not record false negatives in cache."""
        cfg = BarcoIDConfig(
            cache_dir=self.cache_dir, output_dir=self.work_dir / "results", max_retries=1
        )
        engine = RemoteBlastEngine(cfg, self.cache_manager)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = (
            "<!DOCTYPE html><html><head><title>NCBI BLAST Error</title></head>"
            '<body><p class="error">Too many requests: CPU limit exceeded.</p></body></html>'
        )
        mock_post.return_value = mock_resp

        seq = "ATCGATCGATCGATCG"
        results = engine.identify_sequences([("query1", seq)])

        # Runtime dict should report error/unavailable
        self.assertIn("query1", results)
        self.assertFalse(results["query1"]["has_match"])
        self.assertTrue(
            "failed" in results["query1"].get("status", "").lower()
            or "unavailable" in results["query1"].get("status", "").lower()
        )

        # CRITICAL: Persistent cache must NOT have an empty record for this sequence
        cached_val = self.cache_manager.get_ncbi(seq)
        self.assertIsNone(cached_val, "Failed NCBI queries must not be cached as negative hits!")

    def test_pipeline_skip_ncbi_mode(self):
        """Verifies pipeline runs cleanly when skip_ncbi=True."""
        cfg = BarcoIDConfig(
            cache_dir=self.cache_dir,
            output_dir=self.work_dir / "results",
            skip_ncbi=True,
        )
        pipeline = BarcoIDPipeline(cfg)

        seq = "ATCG" * 15
        pipeline.cache_manager.set_bold(
            seq,
            {
                "has_match": True,
                "hit_count": 1,
                "top_genus": "Polyrhachis",
                "top_species": "Polyrhachis dives",
                "top_pct_identity": 99.1,
                "all_hits": [],
            },
        )
        pipeline.cache_manager.set_gbif(
            "Polyrhachis dives",
            {"canonicalName": "Polyrhachis dives", "status": "ACCEPTED"},
        )
        pipeline.cache_manager.save()

        fasta = self.work_dir / "sample.fasta"
        fasta.write_text(f">POLY01_specimen\n{seq}\n", encoding="utf-8")

        rows = pipeline.run(fasta)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["consensus_genus"], "Polyrhachis")
        self.assertEqual(rows[0]["concordance_status"], "NEW_ASSIGNMENT")
        self.assertEqual(rows[0]["qc_flag"], "OK")


if __name__ == "__main__":
    unittest.main()
