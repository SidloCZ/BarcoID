"""
Persistent disk caching for BarcoID external API requests.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional


class CacheManager:
    """Manages persistent JSON caching on disk for external authority queries."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.bold_cache_file = self.cache_dir / "bold_v5_cache.json"
        self.ncbi_cache_file = self.cache_dir / "ncbi_blast_cache.json"
        self.gbif_cache_file = self.cache_dir / "gbif_species_cache.json"

        self.bold_cache: Dict[str, Any] = self._load(self.bold_cache_file)
        self.ncbi_cache: Dict[str, Any] = self._load(self.ncbi_cache_file)
        self.gbif_cache: Dict[str, Any] = self._load(self.gbif_cache_file)

    @staticmethod
    def hash_sequence(sequence: str) -> str:
        """Computes deterministic SHA-256 hash for a nucleotide sequence."""
        return hashlib.sha256(sequence.strip().upper().encode("utf-8")).hexdigest()

    def _load(self, path: Path) -> Dict[str, Any]:
        """Loads cache file from disk safely."""
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save(self):
        """Flushes in-memory cache to disk atomically."""
        self._atomic_save(self.bold_cache_file, self.bold_cache)
        self._atomic_save(self.ncbi_cache_file, self.ncbi_cache)
        self._atomic_save(self.gbif_cache_file, self.gbif_cache)

    @staticmethod
    def _atomic_save(path: Path, data: Dict[str, Any]):
        temp_file = path.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(path)
        except Exception:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)

    def get_bold(self, sequence: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached BOLD result for a sequence."""
        return self.bold_cache.get(self.hash_sequence(sequence))

    def set_bold(self, sequence: str, result: Dict[str, Any]):
        """Caches BOLD result for a sequence."""
        self.bold_cache[self.hash_sequence(sequence)] = result

    def get_ncbi(self, sequence: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached NCBI BLAST result for a sequence."""
        return self.ncbi_cache.get(self.hash_sequence(sequence))

    def set_ncbi(self, sequence: str, result: Dict[str, Any]):
        """Caches NCBI BLAST result for a sequence."""
        self.ncbi_cache[self.hash_sequence(sequence)] = result

    def get_gbif(self, taxon_name: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached GBIF species match result for a taxon name."""
        return self.gbif_cache.get(taxon_name.strip().lower())

    def set_gbif(self, taxon_name: str, result: Dict[str, Any]):
        """Caches GBIF species match result for a taxon name."""
        self.gbif_cache[taxon_name.strip().lower()] = result
