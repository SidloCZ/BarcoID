"""
BOLD Systems v5 REST API client with batching, polling, rate limiting, and disk caching.
"""

import json
import logging
import time
from typing import Any, Dict, List, Tuple

import requests

from barcoid.cache import CacheManager
from barcoid.config import BarcoIDConfig
from barcoid.engines.rate_limiter import RateLimiter, execute_with_backoff

logger = logging.getLogger("barcoid.engines.bold")


class BoldEngine:
    """Client for BOLD Systems v5 Identification Engine."""

    def __init__(self, config: BarcoIDConfig, cache_manager: CacheManager):
        self.config = config
        self.cache_manager = cache_manager
        self.rate_limiter = RateLimiter(min_interval_seconds=config.bold_delay_between_batches)

    def identify_sequences(self, sequences: List[Tuple[str, str]]) -> Dict[str, Dict[str, Any]]:
        """
        Identifies a list of (header, sequence) tuples via BOLD Systems v5 REST API.
        Uses cached results when available to minimize network load.
        """
        results: Dict[str, Dict[str, Any]] = {}
        pending: List[Tuple[str, str, str]] = []

        # Check disk cache first
        for hdr, seq in sequences:
            seq_hash = self.cache_manager.hash_sequence(seq)
            cached = self.cache_manager.get_bold(seq)
            if cached and not self.config.force_refresh:
                results[hdr] = cached
            else:
                pending.append((hdr, seq, seq_hash))

        if not pending or self.config.dry_run:
            if self.config.dry_run and pending:
                logger.info(f"[Dry Run] Skipping {len(pending)} uncached BOLD queries.")
            return results

        logger.info(
            f"Querying BOLD Systems v5 for {len(pending)} uncached sequence(s) "
            f"(batch size: {self.config.bold_batch_size})..."
        )

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BarcoID-BOLD-Client/1.0"
        }
        params = {
            "db": self.config.bold_db,
            "mi": self.config.bold_min_identity,
            "mo": 100,
            "maxh": 25,
            "order": 3,
        }

        batch_size = max(1, self.config.bold_batch_size)
        for i in range(0, len(pending), batch_size):
            chunk = pending[i : i + batch_size]
            self.rate_limiter.wait()

            fasta_body = "".join(f">{hdr}\n{seq}\n" for hdr, seq, _ in chunk)
            files = {"fasta_file": ("batch.fas", fasta_body, "text/plain")}

            def _submit(f=files):
                resp = requests.post(
                    self.config.bold_api_url,
                    params=params,
                    files=f,
                    headers=headers,
                    timeout=60,
                )
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"BOLD submission returned HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                return resp.json()

            try:
                sub_data = execute_with_backoff(
                    _submit,
                    max_retries=self.config.max_retries,
                    backoff_factor=self.config.backoff_factor,
                    action_name=f"BOLD batch {i // batch_size + 1}",
                )
                sub_id = sub_data.get("sub_id")
                if not sub_id:
                    logger.warning(f"No sub_id received from BOLD for batch: {sub_data}")
                    self._populate_empty(chunk, results)
                    continue

                # Poll for batch results
                poll_results = self._poll_results(sub_id, headers, len(chunk))
                for hdr, seq, _seq_hash in chunk:
                    res_obj = poll_results.get(hdr) or self._empty_result()
                    self.cache_manager.set_bold(seq, res_obj)
                    results[hdr] = res_obj

                self.cache_manager.save()

            except Exception as e:
                logger.error(f"Failed processing BOLD batch {i // batch_size + 1}: {e}")
                self._populate_empty(chunk, results)

        return results

    def _poll_results(
        self, sub_id: str, headers: Dict[str, str], expected_count: int
    ) -> Dict[str, Dict[str, Any]]:
        poll_url = f"{self.config.bold_api_url}/results/{sub_id}"
        elapsed = 0
        batch_results: Dict[str, Dict[str, Any]] = {}

        while elapsed < self.config.bold_timeout:
            time.sleep(3)
            elapsed += 3
            try:
                r_poll = requests.get(poll_url, headers=headers, timeout=60)
                if r_poll.status_code == 200 and len(r_poll.text.strip()) > 0:
                    for line in r_poll.text.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            seqid = record.get("seqid")
                            res_obj = self._parse_bold_record(record)
                            if seqid:
                                batch_results[seqid] = res_obj
                        except json.JSONDecodeError:
                            continue
                    return batch_results
            except Exception as poll_err:
                logger.debug(f"BOLD poll iteration error: {poll_err}")

        logger.warning(f"BOLD batch {sub_id} polling timed out after {self.config.bold_timeout}s")
        return batch_results

    def _parse_bold_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        raw_hits = record.get("results", {})
        parsed_hits = []

        for hit_key, hit_val in raw_hits.items():
            key_parts = hit_key.split("|")
            proc_id = key_parts[0] if len(key_parts) > 0 else ""
            bin_uri = key_parts[2] if len(key_parts) > 2 else ""
            pdist = hit_val.get("pdist", 100.0)
            pident = 100.0 - pdist if pdist is not None else 0.0
            tax = hit_val.get("taxonomy", {})

            parsed_hits.append(
                {
                    "process_id": proc_id,
                    "bin_uri": bin_uri,
                    "pct_identity": round(pident, 2),
                    "bitscore": hit_val.get("bitscore", 0),
                    "evalue": hit_val.get("evalue"),
                    "overlap": hit_val.get("overlap", 0),
                    "mismatch": hit_val.get("mismatch", 0),
                    "phylum": tax.get("phylum", ""),
                    "class": tax.get("class", ""),
                    "order": tax.get("order", ""),
                    "family": tax.get("family", ""),
                    "subfamily": tax.get("subfamily", ""),
                    "genus": tax.get("genus", ""),
                    "species": tax.get("species", ""),
                }
            )

        top_hit = parsed_hits[0] if parsed_hits else {}
        top_genus = top_hit.get("genus", "")
        top_species = top_hit.get("species", "")

        if not top_species and top_genus:
            for h in parsed_hits[:5]:
                if h.get("genus") == top_genus and h.get("species"):
                    top_species = h.get("species")
                    break
            if not top_species:
                top_species = f"{top_genus} sp."

        return {
            "has_match": bool(parsed_hits),
            "hit_count": len(parsed_hits),
            "top_genus": top_genus,
            "top_species": top_species,
            "top_pct_identity": top_hit.get("pct_identity", 0.0),
            "top_bin": top_hit.get("bin_uri", ""),
            "top_process_id": top_hit.get("process_id", ""),
            "top_family": top_hit.get("family", ""),
            "top_order": top_hit.get("order", ""),
            "all_hits": parsed_hits,
        }

    def _empty_result(self) -> Dict[str, Any]:
        return {
            "has_match": False,
            "hit_count": 0,
            "top_genus": "",
            "top_species": "",
            "top_pct_identity": 0.0,
            "top_bin": "",
            "top_process_id": "",
            "top_family": "",
            "top_order": "",
            "all_hits": [],
        }

    def _populate_empty(
        self, chunk: List[Tuple[str, str, str]], results: Dict[str, Dict[str, Any]]
    ):
        for hdr, seq, _ in chunk:
            res = self._empty_result()
            results[hdr] = res
            self.cache_manager.set_bold(seq, res)
        self.cache_manager.save()
