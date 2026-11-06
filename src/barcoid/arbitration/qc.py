"""
Quality control (QC) auditor detecting human DNA contamination, cross-well swaps,
low-identity hits, and database conflicts.
"""

from typing import Any, Dict
from barcoid.config import BarcoIDConfig


class QcAuditor:
    """Audits barcode identification results for contamination and anomalies."""

    def __init__(self, config: BarcoIDConfig):
        self.config = config

    def audit(
        self,
        field_genus: str,
        bold_res: Dict[str, Any],
        ncbi_res: Dict[str, Any],
        concordance_status: str,
    ) -> str:
        """
        Determines the appropriate QC Flag for a specimen record.
        Returns:
            One of: 'OK', 'CONTAMINATION_HUMAN', 'CONTAMINATION_SUSPECT',
                    'DATABASE_CONFLICT', 'LOW_IDENTITY', 'LOW_IDENTITY_MISMATCH', 'NO_DATA'
        """
        bold_genus = bold_res.get("top_genus", "").strip()
        ncbi_genus = ncbi_res.get("top_genus", "").strip()
        bold_species = bold_res.get("top_species", "").strip().lower()
        ncbi_species = ncbi_res.get("top_species", "").strip().lower()
        bold_pident = float(bold_res.get("top_pct_identity", 0.0) or 0.0)
        ncbi_pident = float(ncbi_res.get("top_pct_identity", 0.0) or 0.0)
        max_pident = max(bold_pident, ncbi_pident)

        # 1. Human DNA contamination check (Homo sapiens >= 98%)
        if "homo sapiens" in bold_species or "homo sapiens" in ncbi_species:
            if max_pident >= 98.0:
                return "CONTAMINATION_HUMAN"

        # 2. No data check
        if not bold_genus and not ncbi_genus:
            return "NO_DATA"

        # 3. Low identity checks
        is_low_id = 0.0 < max_pident < self.config.low_identity_threshold

        # 4. Mismatch / conflict audits
        if concordance_status == "MISMATCH_ALERT":
            if field_genus:
                # Discrepancy between field and database hits
                if max_pident >= self.config.genus_identity_threshold:
                    return "CONTAMINATION_SUSPECT"
                return "LOW_IDENTITY_MISMATCH"
            else:
                # Discrepancy between BOLD and GenBank
                return "DATABASE_CONFLICT"

        # 5. Low identity warning on concordant or new assignments
        if is_low_id:
            return "LOW_IDENTITY"

        return "OK"
