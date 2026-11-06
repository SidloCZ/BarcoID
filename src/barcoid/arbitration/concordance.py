"""
Concordance arbitration engine evaluating agreement between morphological expectations
and multi-database sequence matches.
"""

from typing import Any, Dict, Tuple
from barcoid.config import BarcoIDConfig


class ConcordanceEngine:
    """Arbitrates taxonomic consensus across morphological priors, BOLD, NCBI, and GBIF."""

    def __init__(self, config: BarcoIDConfig):
        self.config = config

    def evaluate(
        self,
        field_genus: str,
        bold_res: Dict[str, Any],
        ncbi_res: Dict[str, Any],
        gbif_res: Dict[str, Any],
    ) -> Tuple[str, str, str, float]:
        """
        Evaluates agreement across the four evidence streams.
        Returns:
            (consensus_genus, consensus_species, concordance_status, confidence_score)
        """
        bold_genus = bold_res.get("top_genus", "").strip()
        ncbi_genus = ncbi_res.get("top_genus", "").strip()
        bold_pident = float(bold_res.get("top_pct_identity", 0.0) or 0.0)
        ncbi_pident = float(ncbi_res.get("top_pct_identity", 0.0) or 0.0)
        bold_species = bold_res.get("top_species", "").strip()
        ncbi_species = ncbi_res.get("top_species", "").strip()

        # Determine consensus genus
        if bold_genus and ncbi_genus and bold_genus.lower() == ncbi_genus.lower():
            consensus_genus = bold_genus
        elif bold_genus and bold_pident >= self.config.genus_identity_threshold:
            consensus_genus = bold_genus
        elif ncbi_genus and ncbi_pident >= self.config.genus_identity_threshold:
            consensus_genus = ncbi_genus
        elif field_genus:
            consensus_genus = field_genus
        elif bold_genus:
            consensus_genus = bold_genus
        elif ncbi_genus:
            consensus_genus = ncbi_genus
        else:
            consensus_genus = "Unassigned"

        # Determine consensus species
        if bold_species and ncbi_species and bold_species.lower() == ncbi_species.lower():
            consensus_species = bold_species
        elif bold_species and bold_pident >= self.config.species_identity_threshold:
            consensus_species = bold_species
        elif ncbi_species and ncbi_pident >= self.config.species_identity_threshold:
            consensus_species = ncbi_species
        elif consensus_genus != "Unassigned":
            consensus_species = f"{consensus_genus} sp."
        else:
            consensus_species = "Unassigned"

        max_pident = max(bold_pident, ncbi_pident)

        # No match case
        if not bold_genus and not ncbi_genus:
            return consensus_genus, consensus_species, "NO_MATCH", 0.0

        # Field genus was available
        if field_genus:
            bold_mismatch = bool(bold_genus and field_genus.lower() != bold_genus.lower())
            ncbi_mismatch = bool(ncbi_genus and field_genus.lower() != ncbi_genus.lower())

            if bold_mismatch or ncbi_mismatch:
                status = "MISMATCH_ALERT"
                confidence = max_pident / 100.0 * 0.5  # Lower confidence on conflict
            else:
                status = "CONCORDANT"
                confidence = max_pident / 100.0
        else:
            # Field was unassigned (__ / blank)
            db_mismatch = bool(bold_genus and ncbi_genus and bold_genus.lower() != ncbi_genus.lower())
            if db_mismatch:
                status = "MISMATCH_ALERT"
                confidence = 0.5
            else:
                status = "NEW_ASSIGNMENT"
                confidence = max_pident / 100.0

        return consensus_genus, consensus_species, status, round(confidence, 2)

