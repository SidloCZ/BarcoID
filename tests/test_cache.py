"""
Tests for CacheManager persistent disk cache with thread-safety and recovery.
"""

import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from barcoid.cache import CacheManager


class TestCacheManager(unittest.TestCase):
    """Verifies SHA-256 hashing, disk persistence, and thread-safety of CacheManager."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.temp_dir.name)
        self.cache = CacheManager(self.cache_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_hash_sequence_is_deterministic(self):
        seq1 = "ATCGATCG"
        seq2 = "atcgatcg"
        h1 = CacheManager.hash_sequence(seq1)
        h2 = CacheManager.hash_sequence(seq2)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_bold_cache_set_and_get(self):
        seq = "AAACCCGGGTTT"
        data = {"process_id": "TEST01", "identity": 99.5, "genus": "Camponotus"}
        self.assertIsNone(self.cache.get_bold(seq))
        self.cache.set_bold(seq, data)
        self.assertEqual(self.cache.get_bold(seq), data)

    def test_persistence_across_instances(self):
        seq = "GGGTTAACCC"
        ncbi_data = {"accession": "NC_123456", "identity": 100.0}
        self.cache.set_ncbi(seq, ncbi_data)
        self.cache.save()

        # Reopen cache from disk
        new_cache = CacheManager(self.cache_dir)
        self.assertEqual(new_cache.get_ncbi(seq), ncbi_data)

    def test_gbif_species_caching(self):
        taxon = "Pheidole megacephala"
        match_data = {"usageKey": 132456, "status": "ACCEPTED"}
        self.cache.set_gbif(taxon, match_data)
        self.cache.save()

        new_cache = CacheManager(self.cache_dir)
        self.assertEqual(new_cache.get_gbif("pheidole megacephala"), match_data)
        self.assertEqual(new_cache.get_gbif("PHEIDOLE MEGACEPHALA"), match_data)

    def test_prune_empty_removes_unresolved_records(self):
        valid_bold = {"has_match": True, "top_genus": "Camponotus"}
        empty_bold = {"has_match": False, "top_genus": "", "top_species": ""}
        valid_ncbi = {"has_match": True, "top_genus": "Lasius"}
        empty_ncbi = {"has_match": False, "top_genus": "", "top_species": ""}

        self.cache.set_bold("ACGT1", valid_bold)
        self.cache.set_bold("ACGT2", empty_bold)
        self.cache.set_ncbi("ACGT3", valid_ncbi)
        self.cache.set_ncbi("ACGT4", empty_ncbi)
        self.cache.save()

        stats = self.cache.prune_empty()
        self.assertEqual(stats["bold"], 1)
        self.assertEqual(stats["ncbi"], 1)

        self.assertIsNotNone(self.cache.get_bold("ACGT1"))
        self.assertIsNone(self.cache.get_bold("ACGT2"))
        self.assertIsNotNone(self.cache.get_ncbi("ACGT3"))
        self.assertIsNone(self.cache.get_ncbi("ACGT4"))

    def test_concurrent_multi_threaded_cache_saves(self):
        """Simulates parallel BOLD, NCBI, and GBIF background threads saving concurrently."""

        def _bold_worker():
            for i in range(25):
                self.cache.set_bold(f"SEQ_BOLD_{i}", {"has_match": True, "top_genus": f"Genus{i}"})
                self.cache.save_bold()

        def _ncbi_worker():
            for i in range(25):
                self.cache.set_ncbi(f"SEQ_NCBI_{i}", {"has_match": True, "top_genus": f"Genus{i}"})
                self.cache.save_ncbi()

        def _gbif_worker():
            for i in range(25):
                self.cache.set_gbif(f"Taxon_{i}", {"canonicalName": f"Taxon {i}", "usageKey": i})
                self.cache.save_gbif()

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = [
                pool.submit(_bold_worker),
                pool.submit(_ncbi_worker),
                pool.submit(_gbif_worker),
                pool.submit(_bold_worker),
                pool.submit(_ncbi_worker),
                pool.submit(_gbif_worker),
            ]
            for f in futures:
                f.result()

        # Reopen to verify no data loss or file corruption occurred
        reopened = CacheManager(self.cache_dir)
        self.assertEqual(len(reopened.bold_cache), 25)
        self.assertEqual(len(reopened.ncbi_cache), 25)
        self.assertEqual(len(reopened.gbif_cache), 25)


if __name__ == "__main__":
    unittest.main()
