"""
FASTA reader and sequence validator for BarcoID with workload limiting.
"""

import gzip
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from Bio import SeqIO

logger = logging.getLogger("barcoid.parsers.fasta")


class FastaParser:
    """Reads and validates nucleotide sequences from FASTA files."""

    @staticmethod
    def read_sequences(
        fasta_path: Path, max_sequences: Optional[int] = None
    ) -> List[Tuple[str, str]]:
        """
        Parses FASTA sequences. If max_sequences is set, caps the returned list to prevent
        accidental high-volume server overloads.
        """
        fasta_path = Path(fasta_path)
        if not fasta_path.exists():
            raise FileNotFoundError(f"Input FASTA file not found: {fasta_path}")

        records: List[Tuple[str, str]] = []
        opener = gzip.open if fasta_path.suffix.lower() == ".gz" else open

        with opener(fasta_path, "rt", encoding="utf-8", errors="replace") as handle:
            for record in SeqIO.parse(handle, "fasta"):
                hdr = record.description.strip()
                seq = str(record.seq).strip().upper()
                if seq:
                    records.append((hdr, seq))
                    if max_sequences and len(records) >= max_sequences:
                        logger.info(
                            f"Capped input at {max_sequences} sequences (max_sequences limit reached)."
                        )
                        break

        logger.info(f"Loaded {len(records)} sequence(s) from {fasta_path.name}")
        return records

    @staticmethod
    def compute_summary_stats(sequences: List[Tuple[str, str]]) -> dict:
        """Computes summary metrics (count, lengths, ambiguities) for a sequence set."""
        if not sequences:
            return {"count": 0, "min_len": 0, "max_len": 0, "mean_len": 0, "ambiguous_count": 0}

        lengths = [len(seq) for _, seq in sequences]
        amb_count = sum(1 for _, seq in sequences if "N" in seq)

        return {
            "count": len(sequences),
            "min_len": min(lengths),
            "max_len": max(lengths),
            "mean_len": round(sum(lengths) / len(lengths), 1),
            "ambiguous_count": amb_count,
        }
