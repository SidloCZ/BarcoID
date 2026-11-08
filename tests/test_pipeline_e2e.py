"""
End-to-end integration tests for BarcoIDPipeline with disk caching.
"""

import tempfile
import unittest
from pathlib import Path

from barcoid.config import BarcoIDConfig
from barcoid.pipeline import BarcoIDPipeline


class TestPipelineE2E(unittest.TestCase):
    """Tests end-to-end pipeline execution and file export."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)
        self.cache_dir = self.work_dir / ".id_cache"
        self.output_dir = self.work_dir / "results"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_pipeline_cached_execution(self):
        config = BarcoIDConfig(cache_dir=self.cache_dir, output_dir=self.output_dir)
        pipeline = BarcoIDPipeline(config)

        # Pre-seed cache with test sequences
        seq1 = "ATCGATCGATCGATCG"

        pipeline.cache_manager.set_bold(
            seq1,
            {
                "has_match": True,
                "hit_count": 1,
                "top_genus": "Pheidole",
                "top_species": "Pheidole oceanica",
                "top_pct_identity": 99.5,
                "top_bin": "BOLD:AAA1111",
                "top_process_id": "TEST_001",
                "all_hits": [],
            },
        )
        pipeline.cache_manager.set_ncbi(
            seq1,
            {
                "has_match": True,
                "hit_count": 1,
                "top_title": "Pheidole oceanica COI",
                "top_accession": "AB123456",
                "top_genus": "Pheidole",
                "top_species": "Pheidole oceanica",
                "top_pct_identity": 99.4,
                "top_evalue": 0.0,
                "top_bitscore": 120.0,
                "all_hits": [],
            },
        )
        pipeline.cache_manager.set_gbif(
            "Pheidole oceanica",
            {
                "usageKey": 12345,
                "canonicalName": "Pheidole oceanica",
                "rank": "SPECIES",
                "status": "ACCEPTED",
                "confidence": 99,
            },
        )
        pipeline.cache_manager.save()

        # Write test FASTA file
        fasta_path = self.work_dir / "test_barcodes.fasta"
        with open(fasta_path, "w", encoding="utf-8") as f:
            f.write(
                f">MJB0001426_MJB016_redo3_Valavahalo_2017_PHEI01_GUA0444;313;41;ambs=0;estgaps=0\n{seq1}\n"
            )

        # Run pipeline
        rows = pipeline.run(fasta_path)

        self.assertEqual(len(rows), 1)
        res = rows[0]
        self.assertEqual(res["consensus_genus"], "Pheidole")
        self.assertEqual(res["concordance_status"], "CONCORDANT")
        self.assertEqual(res["qc_flag"], "OK")

        # Verify exported files exist
        xlsx_file = self.output_dir / "test_barcodes_multi_source_identification.xlsx"
        tsv_file = self.output_dir / "test_barcodes_identification.tsv"
        report_file = self.output_dir / "test_barcodes_qc_report.md"

        self.assertTrue(xlsx_file.exists())
        self.assertTrue(tsv_file.exists())
        self.assertTrue(report_file.exists())
        self.assertGreater(xlsx_file.stat().st_size, 1000)
        self.assertGreater(tsv_file.stat().st_size, 50)
        self.assertGreater(report_file.stat().st_size, 100)


if __name__ == "__main__":
    unittest.main()
