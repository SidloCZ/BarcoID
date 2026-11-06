"""
Tests for CacheManager persistent disk cache.
"""

import tempfile
import unittest
from pathlib import Path
from barcoid.cache import CacheManager


class TestCacheManager(unittest.TestCase):
    """Verifies SHA-256 hashing and disk persistence of CacheManager."""

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


if __name__ == "__main__":
    unittest.main()

