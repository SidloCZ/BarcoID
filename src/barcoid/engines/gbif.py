"""
GBIF Taxonomic Backbone Species Match client with deduplication, rate limiting, and disk caching.

Note on GBIF & Sequence Data:
While GBIF provides a web-based Sequence ID (SeqID) tool on its portal that wraps BLAST+
against third-party databases (BOLD, MIDORI, UNITE), GBIF does not expose an official public
batch sequence alignment REST API. In the BarcoID pipeline, primary sequence alignment is performed
directly against BOLD Systems v5 and NCBI GenBank, while the GbifEngine utilizes GBIF's official
Taxonomic Backbone API (`/v1/species/match`) as the nomenclatural authority to validate accepted
taxa, resolve junior synonyms, and standardize classifications across databases.
"""

import logging
from typing import Any, Dict, List

import requests

from barcoid.cache import CacheManager
from barcoid.config import BarcoIDConfig
from barcoid.engines.rate_limiter import RateLimiter, execute_with_backoff

logger = logging.getLogger("barcoid.engines.gbif")


class GbifEngine:
    """Standardizes taxonomic names against the GBIF Taxonomic Backbone API."""

    def __init__(self, config: BarcoIDConfig, cache_manager: CacheManager):
        self.config = config
        self.cache_manager = cache_manager
        self.rate_limiter = RateLimiter(min_interval_seconds=config.gbif_delay_between_requests)

    def match_species(self, name: str) -> Dict[str, Any]:
        """
        Queries GBIF species match API for a single name, using cache when available.
        """
        if not name or not name.strip():
            return {}

        clean_name = name.strip()
        cached = self.cache_manager.get_gbif(clean_name)
        if cached and not self.config.force_refresh:
            return cached

        if self.config.dry_run:
            return {}

        self.rate_limiter.wait()
        params = {"name": clean_name}
        if self.config.gbif_kingdom:
            params["kingdom"] = self.config.gbif_kingdom

        def _do_query():
            resp = requests.get(
                self.config.gbif_species_match_url,
                params=params,
                timeout=15,
            )
            if resp.status_code == 429:
                raise RuntimeError("GBIF returned HTTP 429: Too Many Requests.")
            if resp.status_code != 200:
                raise RuntimeError(f"GBIF query failed with HTTP {resp.status_code}")
            return resp.json()

        try:
            data = execute_with_backoff(
                _do_query,
                max_retries=self.config.max_retries,
                backoff_factor=self.config.backoff_factor,
                action_name=f"GBIF match for '{clean_name}'",
            )
            result = {
                "usageKey": data.get("usageKey"),
                "scientificName": data.get("scientificName", ""),
                "canonicalName": data.get("canonicalName", ""),
                "rank": data.get("rank", ""),
                "status": data.get("status", ""),
                "confidence": data.get("confidence", 0),
                "matchType": data.get("matchType", ""),
                "genus": data.get("genus", ""),
                "family": data.get("family", ""),
                "order": data.get("order", ""),
            }
            self.cache_manager.set_gbif(clean_name, result)
            self.cache_manager.save_gbif()
            return result
        except Exception as e:
            logger.warning(f"GBIF Species Match failed for '{clean_name}': {e}")
            return {}

    def match_batch(self, names: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Matches a list of names, deduplicating uncached queries to protect GBIF API limits.
        """
        results: Dict[str, Dict[str, Any]] = {}
        unique_names = sorted(list(set(n.strip() for n in names if n and n.strip())))

        for name in unique_names:
            results[name] = self.match_species(name)

        self.cache_manager.save_gbif()
        return results
