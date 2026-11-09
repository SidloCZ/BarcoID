"""
Resilient NCBI GenBank QBLAST remote client with stalled RID recovery, adaptive batching,
defline sanitization, HTML error detection, and compliance pacing.
"""

import io
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from Bio.Blast import NCBIXML

from barcoid.cache import CacheManager
from barcoid.config import BarcoIDConfig
from barcoid.engines.rate_limiter import RateLimiter, execute_with_backoff

logger = logging.getLogger("barcoid.engines.blast_remote")

# Regex to sanitize and extract GenBank identifiers and taxonomic names from BLAST hit titles
GENBANK_TITLE_REGEX = re.compile(
    r">?gi\|\d+\|(?:gb|emb|dbj|tpg|ref)\|([\w\.]+)\|\s*(?:TPA(?:_asm)?:\s*|UNVERIFIED:\s*|PREDICTED:\s*)?([A-Za-z]+)\s+([A-Za-z0-9\.\_\-]+)"
)


class RemoteBlastEngine:
    """Resilient client for NCBI GenBank nucleotide QBLAST."""

    def __init__(self, config: BarcoIDConfig, cache_manager: CacheManager):
        self.config = config
        self.cache_manager = cache_manager
        # NCBI rate limits: 3 req/s without API key, 10 req/s with API key
        min_interval = 0.35 if config.ncbi_api_key else self.config.ncbi_delay_between_batches
        self.rate_limiter = RateLimiter(min_interval_seconds=min_interval)

    def identify_sequences(self, sequences: List[Tuple[str, str]]) -> Dict[str, Dict[str, Any]]:
        """
        Submits sequences to NCBI QBLAST in small batches with strict timeouts
        and maps results back to original sequence headers.
        """
        results: Dict[str, Dict[str, Any]] = {}
        pending: List[Tuple[str, str, str]] = []

        for hdr, seq in sequences:
            seq_hash = self.cache_manager.hash_sequence(seq)
            cached = self.cache_manager.get_ncbi(seq)
            if cached and not self.config.force_refresh:
                results[hdr] = cached
            else:
                pending.append((hdr, seq, seq_hash))

        if not pending or self.config.dry_run:
            if self.config.dry_run and pending:
                logger.info(f"[Dry Run] Skipping {len(pending)} uncached NCBI QBLAST queries.")
            return results

        total_pending = len(pending)
        batch_size = max(1, self.config.ncbi_batch_size)
        logger.info(
            f"Submitting {total_pending} sequence(s) to remote NCBI BLASTn (batch size: {batch_size})..."
        )

        for b_idx in range(0, total_pending, batch_size):
            chunk = pending[b_idx : b_idx + batch_size]
            query_map: Dict[str, Tuple[str, str]] = {}
            fasta_lines: List[str] = []

            for q_num, (hdr, seq, _seq_hash) in enumerate(chunk, start=1):
                qid = f"Q{q_num}"
                query_map[qid] = (hdr, seq)
                fasta_lines.append(f">{qid}\n{seq}\n")

            chunk_fasta = "".join(fasta_lines)
            batch_num = (b_idx // batch_size) + 1
            total_batches = (total_pending + batch_size - 1) // batch_size

            # Pacing delay between consecutive QBLAST submissions to avoid congestion
            if b_idx > 0 and self.config.ncbi_delay_between_batches > 0:
                delay = self.config.ncbi_delay_between_batches
                logger.info(f"Pacing pause ({delay:.1f}s) before next NCBI QBLAST submission...")
                time.sleep(delay)

            logger.info(
                f"  [Batch {batch_num}/{total_batches}] Querying NCBI for {len(chunk)} sequence(s)..."
            )

            self.rate_limiter.wait()
            try:
                xml_text = self._qblast_xml(chunk_fasta)
                if xml_text:
                    records = list(NCBIXML.parse(io.StringIO(xml_text)))
                    for rec in records:
                        qid = rec.query.split()[0] if rec.query else ""
                        if qid not in query_map:
                            continue
                        orig_hdr, orig_seq = query_map[qid]
                        res_obj = self._parse_blast_record(rec)
                        self.cache_manager.set_ncbi(orig_seq, res_obj)
                        results[orig_hdr] = res_obj

                    # Fill genuine unaligned queries (present in valid XML but with 0 alignments)
                    for _qid, (orig_hdr, orig_seq) in query_map.items():
                        if orig_hdr not in results:
                            empty_res = self._empty_result()
                            self.cache_manager.set_ncbi(orig_seq, empty_res)
                            results[orig_hdr] = empty_res

                    self.cache_manager.save_ncbi()
                else:
                    logger.warning(
                        f"NCBI QBLAST batch {batch_num} yielded no XML (API error/timeout). "
                        "Results will NOT be cached as negative matches."
                    )
                    for _qid, (orig_hdr, _orig_seq) in query_map.items():
                        if orig_hdr not in results:
                            err_res = self._empty_result()
                            err_res["status"] = "NCBI query timed out or unavailable"
                            err_res["failed"] = True
                            err_res["error"] = "Timeout"
                            results[orig_hdr] = err_res
                    # Cool-down pause to allow remote NCBI queue to recover
                    time.sleep(12.0)

            except Exception as e:
                logger.error(f"NCBI QBLAST batch {batch_num} failed: {e}")
                for _qid, (orig_hdr, _orig_seq) in query_map.items():
                    if orig_hdr not in results:
                        err_res = self._empty_result()
                        err_res["status"] = f"NCBI batch failed: {e}"
                        err_res["failed"] = True
                        err_res["error"] = str(e)
                        results[orig_hdr] = err_res
                # Cool-down pause to allow remote NCBI queue to recover
                time.sleep(12.0)

        return results

    def _qblast_xml(self, fasta_str: str) -> Optional[str]:
        """Submits QBLAST request and polls for XML output with timeout protection."""
        url = "https://blast.ncbi.nlm.nih.gov/Blast.cgi"
        put_params = {
            "CMD": "Put",
            "PROGRAM": self.config.ncbi_program,
            "DATABASE": self.config.ncbi_database,
            "MEGABLAST": "on" if self.config.megablast else "off",
            "ENTREZ_QUERY": self.config.ncbi_entrez_query,
            "HITLIST_SIZE": str(self.config.ncbi_hitlist_size),
            "QUERY": fasta_str,
            "EMAIL": self.config.ncbi_email or "barcoid_user@example.com",
            "TOOL": "BarcoID",
        }
        if self.config.ncbi_api_key:
            put_params["API_KEY"] = self.config.ncbi_api_key

        def _do_put():
            resp = requests.post(url, data=put_params, timeout=30)
            if resp.status_code == 429:
                raise RuntimeError("NCBI returned HTTP 429: Too Many Requests.")
            if resp.status_code != 200:
                raise RuntimeError(f"NCBI Put failed with HTTP {resp.status_code}")
            text = resp.text
            if "RID = " not in text:
                lower = text.lower()
                if (
                    "<html" in lower
                    or "too many requests" in lower
                    or "cpu limit" in lower
                    or "cannot submit" in lower
                ):
                    raise RuntimeError(
                        "NCBI QBLAST server busy / rate-limited (returned HTML error page without RID)."
                    )
                raise RuntimeError(f"NCBI Put did not return RID: {text[:200]}")
            return text

        put_text = execute_with_backoff(
            _do_put,
            max_retries=self.config.max_retries,
            backoff_factor=self.config.backoff_factor,
            action_name="NCBI QBLAST Put",
        )

        m_rid = re.search(r"RID = (\w+)", put_text)
        m_rtoe = re.search(r"RTOE = (\d+)", put_text)
        if not m_rid:
            logger.warning(f"Failed to obtain NCBI Request ID (RID): {put_text[:200]}")
            return None

        rid = m_rid.group(1)
        rtoe = int(m_rtoe.group(1)) if m_rtoe else 15
        time.sleep(min(max(rtoe, 12), 30))

        elapsed = 0
        poll_interval = max(8, self.config.ncbi_poll_interval)
        while elapsed < self.config.ncbi_timeout:
            poll_params = {"CMD": "Get", "FORMAT_OBJECT": "SearchInfo", "RID": rid}
            if self.config.ncbi_api_key:
                poll_params["API_KEY"] = self.config.ncbi_api_key

            r_check = requests.get(url, params=poll_params, timeout=30)
            if "Status=WAITING" in r_check.text:
                time.sleep(poll_interval)
                elapsed += poll_interval
                continue
            elif "Status=FAILED" in r_check.text:
                logger.warning(f"NCBI Search RID {rid} reported FAILED.")
                return None
            elif "Status=UNKNOWN" in r_check.text:
                logger.warning(f"NCBI Search RID {rid} reported UNKNOWN / expired.")
                return None
            elif "Status=READY" in r_check.text:
                get_params = {"CMD": "Get", "FORMAT_TYPE": "XML", "RID": rid}
                if self.config.ncbi_api_key:
                    get_params["API_KEY"] = self.config.ncbi_api_key
                r_xml = requests.get(url, params=get_params, timeout=60)
                return r_xml.text

        logger.warning(
            f"NCBI Search RID {rid} stalled and timed out after {self.config.ncbi_timeout}s."
        )
        return None

    def _parse_blast_record(self, record: Any) -> Dict[str, Any]:
        hits: List[Dict[str, Any]] = []
        for alignment in record.alignments:
            hsp = alignment.hsps[0]
            pct_id = (hsp.identities / hsp.align_length) * 100.0 if hsp.align_length > 0 else 0.0

            title = alignment.title
            m_tax = GENBANK_TITLE_REGEX.search(title)
            accession = alignment.accession
            genus = ""
            species = ""

            if m_tax:
                accession = m_tax.group(1)
                genus = m_tax.group(2)
                species_token = m_tax.group(3)
                species = f"{genus} {species_token}"
            else:
                # Fallback tokenization
                clean_title = re.sub(
                    r"^(?:TPA(?:_asm)?:\s*|UNVERIFIED:\s*|PREDICTED:\s*)", "", title.strip()
                )
                words = clean_title.split()
                if len(words) >= 2 and words[0].isalpha():
                    genus = words[0]
                    species = f"{words[0]} {words[1]}"

            hits.append(
                {
                    "accession": accession,
                    "title": title,
                    "pct_identity": round(pct_id, 2),
                    "evalue": hsp.expect,
                    "bitscore": hsp.bits,
                    "alignment_length": hsp.align_length,
                    "genus": genus,
                    "species": species,
                }
            )

        top_hit = hits[0] if hits else {}
        return {
            "has_match": bool(hits),
            "hit_count": len(hits),
            "top_title": top_hit.get("title", ""),
            "top_accession": top_hit.get("accession", ""),
            "top_genus": top_hit.get("genus", ""),
            "top_species": top_hit.get("species", ""),
            "top_pct_identity": top_hit.get("pct_identity", 0.0),
            "top_evalue": top_hit.get("evalue"),
            "top_bitscore": top_hit.get("bitscore", 0.0),
            "all_hits": hits,
        }

    def _empty_result(self) -> Dict[str, Any]:
        return {
            "has_match": False,
            "hit_count": 0,
            "top_title": "",
            "top_accession": "",
            "top_genus": "",
            "top_species": "",
            "top_pct_identity": 0.0,
            "top_evalue": None,
            "top_bitscore": 0.0,
            "all_hits": [],
        }
