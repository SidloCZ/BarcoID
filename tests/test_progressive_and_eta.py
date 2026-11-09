"""
Unit and integration tests for progressive chunking, preliminary Excel exports,
dynamic ETA estimation, and live GUI navigation.
"""

import tempfile
import unittest
from pathlib import Path

from barcoid.config import BarcoIDConfig
from barcoid.gui import BarcoIDApp
from barcoid.pipeline import BarcoIDPipeline


class TestProgressiveAndEta(unittest.TestCase):
    """Verifies incremental chunking, preliminary callbacks, and ETA metrics."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)
        self.cache_dir = self.work_dir / ".id_cache"
        self.out_dir = self.work_dir / "results"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_progressive_chunking_and_preliminary_callback(self):
        """Verifies that preliminary callback and preliminary Excel file are created during chunked execution."""
        cfg = BarcoIDConfig(
            cache_dir=self.cache_dir,
            output_dir=self.out_dir,
            skip_ncbi=True,
            enable_preliminary_results=True,
            preliminary_interval=2,  # 2 sequences per chunk
        )
        pipeline = BarcoIDPipeline(cfg)

        # Pre-seed BOLD & GBIF cache for 4 sequences
        seqs = [f"ATCGATCG{i}" * 5 for i in range(4)]
        for i, s in enumerate(seqs):
            pipeline.cache_manager.set_bold(
                s,
                {
                    "has_match": True,
                    "hit_count": 1,
                    "top_genus": "Camponotus",
                    "top_species": f"Camponotus species_{i}",
                    "top_pct_identity": 99.0,
                    "all_hits": [],
                },
            )
            pipeline.cache_manager.set_gbif(
                f"Camponotus species_{i}",
                {"canonicalName": f"Camponotus species_{i}", "status": "ACCEPTED"},
            )
        pipeline.cache_manager.save()

        fasta_path = self.work_dir / "chunk_test.fasta"
        with open(fasta_path, "w", encoding="utf-8") as f:
            for i, s in enumerate(seqs):
                f.write(f">CAMP_{i}\n{s}\n")

        prelim_events = []
        progress_metrics = []

        def _on_prelim(rows, path):
            prelim_events.append((len(rows), path))

        def _on_prog(stage, pct, metrics=None):
            if metrics:
                progress_metrics.append(metrics)

        final_rows = pipeline.run(
            fasta_path=fasta_path,
            progress_callback=_on_prog,
            preliminary_callback=_on_prelim,
        )

        self.assertEqual(len(final_rows), 4)
        # Should have received preliminary events (chunk 1 with 2 rows, etc.)
        self.assertGreaterEqual(len(prelim_events), 1)
        self.assertEqual(prelim_events[0][0], 2)
        self.assertTrue(prelim_events[0][1].exists())

        # Verify ETA metrics structure
        self.assertTrue(len(progress_metrics) >= 1)
        m = progress_metrics[0]
        self.assertIn("completed", m)
        self.assertIn("total", m)
        self.assertIn("speed", m)
        self.assertIn("eta_seconds", m)
        self.assertIn("elapsed_seconds", m)
        self.assertEqual(m["total"], 4)

    def test_preliminary_disabled_does_not_export_preliminary_file(self):
        """Verifies that setting enable_preliminary_results=False skips writing preliminary Excel."""
        cfg = BarcoIDConfig(
            cache_dir=self.cache_dir,
            output_dir=self.out_dir,
            skip_ncbi=True,
            enable_preliminary_results=False,
            preliminary_interval=2,
        )
        pipeline = BarcoIDPipeline(cfg)

        seqs = [f"ATCG{i}" * 8 for i in range(4)]
        for i, s in enumerate(seqs):
            pipeline.cache_manager.set_bold(
                s,
                {
                    "has_match": True,
                    "hit_count": 1,
                    "top_genus": "Lasius",
                    "top_species": f"Lasius niger_{i}",
                    "top_pct_identity": 99.2,
                    "all_hits": [],
                },
            )
        pipeline.cache_manager.save()

        fasta_path = self.work_dir / "no_prelim.fasta"
        with open(fasta_path, "w", encoding="utf-8") as f:
            for i, s in enumerate(seqs):
                f.write(f">LAS_{i}\n{s}\n")

        prelim_files = []

        def _on_prelim(rows, path):
            prelim_files.append(path)

        pipeline.run(fasta_path=fasta_path, preliminary_callback=_on_prelim)

        prelim_path = self.out_dir / "no_prelim_preliminary.xlsx"
        self.assertFalse(prelim_path.exists())

    def test_duration_formatting(self):
        """Verifies duration formatting for MM:SS and HH:MM:SS."""
        self.assertEqual(BarcoIDApp._format_duration(45), "00:45")
        self.assertEqual(BarcoIDApp._format_duration(125), "02:05")
        self.assertEqual(BarcoIDApp._format_duration(3665), "01:01:05")


if __name__ == "__main__":
    unittest.main()

