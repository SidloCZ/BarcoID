"""
Persistent disk caching for BarcoID external API requests with thread safety and atomic writes.
"""

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("barcoid.cache")


class CacheManager:
    """Manages persistent JSON caching on disk for external authority queries with thread safety."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.bold_cache_file = self.cache_dir / "bold_v5_cache.json"
        self.ncbi_cache_file = self.cache_dir / "ncbi_blast_cache.json"
        self.gbif_cache_file = self.cache_dir / "gbif_species_cache.json"

        self._lock = threading.RLock()
        self._bold_dirty = False
        self._ncbi_dirty = False
        self._gbif_dirty = False

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
            except Exception as e:
                logger.warning(f"Could not load cache from {path}: {e}")
                return {}
        return {}

    def save(self):
        """Flushes all dirty in-memory caches to disk atomically."""
        with self._lock:
            self.save_bold()
            self.save_ncbi()
            self.save_gbif()

    def save_bold(self):
        """Flushes BOLD in-memory cache to disk if modified."""
        with self._lock:
            if self._bold_dirty:
                self._atomic_save(self.bold_cache_file, self.bold_cache)
                self._bold_dirty = False

    def save_ncbi(self):
        """Flushes NCBI in-memory cache to disk if modified."""
        with self._lock:
            if self._ncbi_dirty:
                self._atomic_save(self.ncbi_cache_file, self.ncbi_cache)
                self._ncbi_dirty = False

    def save_gbif(self):
        """Flushes GBIF in-memory cache to disk if modified."""
        with self._lock:
            if self._gbif_dirty:
                self._atomic_save(self.gbif_cache_file, self.gbif_cache)
                self._gbif_dirty = False

    @staticmethod
    def _atomic_save(path: Path, data: Dict[str, Any]):
        """
        Writes data to a uniquely-named temp file and atomically replaces destination.
        Handles Windows file-locking (OneDrive, antivirus) with exponential retry.
        """
        unique_suffix = f"_{os.getpid()}_{threading.get_ident()}_{uuid.uuid4().hex[:6]}.tmp"
        temp_file = path.with_name(f"{path.stem}{unique_suffix}")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            max_retries = 5
            for attempt in range(max_retries):
                try:
                    temp_file.replace(path)
                    return
                except (PermissionError, OSError) as pe:
                    if attempt == max_retries - 1:
                        # Fallback for Windows file lock collisions (e.g. OneDrive)
                        try:
                            shutil.copyfile(temp_file, path)
                            return
                        except Exception:
                            logger.warning(f"Could not atomically replace cache {path}: {pe}")
                    else:
                        time.sleep(0.05 * (2**attempt))
        except Exception as e:
            logger.warning(f"Failed writing cache to {temp_file}: {e}")
        finally:
            try:
                if temp_file.exists():
                    temp_file.unlink(missing_ok=True)
            except OSError:
                pass

    def get_bold(self, sequence: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached BOLD result for a sequence."""
        with self._lock:
            return self.bold_cache.get(self.hash_sequence(sequence))

    def set_bold(self, sequence: str, result: Dict[str, Any]):
        """Caches BOLD result for a sequence."""
        with self._lock:
            self.bold_cache[self.hash_sequence(sequence)] = result
            self._bold_dirty = True

    def get_ncbi(self, sequence: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached NCBI BLAST result for a sequence."""
        with self._lock:
            return self.ncbi_cache.get(self.hash_sequence(sequence))

    def set_ncbi(self, sequence: str, result: Dict[str, Any]):
        """Caches NCBI BLAST result for a sequence."""
        with self._lock:
            self.ncbi_cache[self.hash_sequence(sequence)] = result
            self._ncbi_dirty = True

    def get_gbif(self, taxon_name: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached GBIF species match result for a taxon name."""
        with self._lock:
            return self.gbif_cache.get(taxon_name.strip().lower())

    def set_gbif(self, taxon_name: str, result: Dict[str, Any]):
        """Caches GBIF species match result for a taxon name."""
        with self._lock:
            self.gbif_cache[taxon_name.strip().lower()] = result
            self._gbif_dirty = True

    def prune_empty(self) -> Dict[str, int]:
        """
        Prunes empty/failed entries from cache so queries can be retried
        without losing valid biological hits.
        """
        with self._lock:
            bold_before = len(self.bold_cache)
            ncbi_before = len(self.ncbi_cache)

            self.bold_cache = {
                k: v
                for k, v in self.bold_cache.items()
                if v.get("has_match") or v.get("top_genus") or v.get("top_species")
            }
            self.ncbi_cache = {
                k: v
                for k, v in self.ncbi_cache.items()
                if v.get("has_match") or v.get("top_genus") or v.get("top_species")
            }

            pruned_bold = bold_before - len(self.bold_cache)
            pruned_ncbi = ncbi_before - len(self.ncbi_cache)

            if pruned_bold > 0:
                self._bold_dirty = True
                self.save_bold()
            if pruned_ncbi > 0:
                self._ncbi_dirty = True
                self.save_ncbi()

            return {"bold": pruned_bold, "ncbi": pruned_ncbi}
