"""
Parser for ONTbarcoder (Srivathsan et al., 2021) consensus FASTA header statistics.
"""

from typing import Any, Dict


class OntbarcoderParser:
    """Parses semicolon-delimited ONTbarcoder assembly metrics from deflines."""

    @staticmethod
    def parse_stats(header: str) -> Dict[str, Any]:
        """
        Extracts sequence length, read coverage, ambiguities, and estimated gaps
        from headers formatted like: `>SampleID;658;45;ambs=0;estgaps=0`.
        """
        clean_hdr = header.lstrip(">").strip()
        parts = clean_hdr.split(";")

        seq_len = 0
        coverage = 0
        ambs = 0
        estgaps = 0

        if len(parts) > 1 and parts[1].isdigit():
            seq_len = int(parts[1])
        if len(parts) > 2 and parts[2].isdigit():
            coverage = int(parts[2])

        for p in parts[3:]:
            if p.startswith("ambs="):
                try:
                    ambs = int(p.split("=")[1])
                except ValueError:
                    pass
            elif p.startswith("estgaps="):
                try:
                    estgaps = int(p.split("=")[1])
                except ValueError:
                    pass

        return {
            "seq_length": seq_len,
            "coverage": coverage,
            "ambiguities": ambs,
            "est_gaps": estgaps,
        }

