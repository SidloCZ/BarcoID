"""
Local blastn subprocess engine for high-throughput, offline DNA barcode identification.
"""

import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple
from Bio.Blast import NCBIXML

from barcoid.cache import CacheManager
from barcoid.config import BarcoIDConfig
from barcoid.engines.blast_remote import GENBANK_TITLE_REGEX

logger = logging.getLogger("barcoid.engines.blast_local")


class LocalBlastEngine:
    """Runs local blastn binary against an indexed nucleotide database."""

    def __init__(self, config: BarcoIDConfig, cache_manager: CacheManager):
        self.config = config
        self.cache_manager = cache_manager
        self.blastn_path = shutil.which("blastn")

    def is_available(self) -> bool:
        """Returns True if local blastn binary and database path are both configured."""
        if not self.blastn_path:
            return False
        if not self.config.local_blast_db:
            return False
        return Path(self.config.local_blast_db).exists()

    def identify_sequences(
        self, sequences: List[Tuple[str, str]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Runs local blastn on sequences and populates the cache.
        """
        results: Dict[str, Dict[str, Any]] = {}
        pending: List[Tuple[str, str, str]] = []

        for hdr, seq in sequences:
            cached = self.cache_manager.get_ncbi(seq)
            if cached and not self.config.force_refresh:
                results[hdr] = cached
            else:
                pending.append((hdr, seq, self.cache_manager.hash_sequence(seq)))

        if not pending or self.config.dry_run:
            return results

        if not self.is_available():
            raise FileNotFoundError(
                f"blastn executable or database '{self.config.local_blast_db}' not found."
            )

        logger.info(
            f"Running local blastn for {len(pending)} sequence(s) against database '{self.config.local_blast_db}'..."
        )

        with tempfile.NamedTemporaryFile("w", suffix=".fasta", delete=False) as q_file:
            query_path = Path(q_file.name)
            query_map: Dict[str, Tuple[str, str]] = {}
            for q_num, (hdr, seq, _) in enumerate(pending, start=1):
                qid = f"Q{q_num}"
                query_map[qid] = (hdr, seq)
                q_file.write(f">{qid}\n{seq}\n")

        try:
            cmd = [
                self.blastn_path,
                "-query", str(query_path),
                "-db", str(self.config.local_blast_db),
                "-outfmt", "5",  # XML format
                "-max_target_seqs", str(self.config.ncbi_hitlist_size),
                "-num_threads", str(self.config.local_blast_threads),
            ]
            if self.config.megablast:
                cmd.extend(["-task", "megablast"])

            proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
            records = list(NCBIXML.parse(io.StringIO(proc.stdout)))

            for rec in records:
                qid = rec.query.split()[0] if rec.query else ""
                if qid not in query_map:
                    continue
                orig_hdr, orig_seq = query_map[qid]
                res_obj = self._parse_local_record(rec)
                self.cache_manager.set_ncbi(orig_seq, res_obj)
                results[orig_hdr] = res_obj

            for qid, (orig_hdr, orig_seq) in query_map.items():
                if orig_hdr not in results:
                    empty_res = self._empty_result()
                    self.cache_manager.set_ncbi(orig_seq, empty_res)
                    results[orig_hdr] = empty_res

            self.cache_manager.save()

        finally:
            query_path.unlink(missing_ok=True)

        return results

    def _parse_local_record(self, record: Any) -> Dict[str, Any]:
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
                species = f"{genus} {m_tax.group(3)}"
            else:
                words = title.strip().split()
                if len(words) >= 2 and words[0].isalpha():
                    genus = words[0]
                    species = f"{words[0]} {words[1]}"

            hits.append({
                "accession": accession,
                "title": title,
                "pct_identity": round(pct_id, 2),
                "evalue": hsp.expect,
                "bitscore": hsp.bits,
                "alignment_length": hsp.align_length,
                "genus": genus,
                "species": species,
            })

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

