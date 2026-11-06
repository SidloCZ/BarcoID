"""
Configuration and default parameters for BarcoID.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


@dataclass
class BarcoIDConfig:
    """Configuration settings for BarcoID execution."""

    # Paths
    cache_dir: Path = field(default_factory=lambda: Path(".id_cache"))
    output_dir: Path = field(default_factory=lambda: Path("results"))

    # BOLD Systems v5 API settings
    bold_api_url: str = "https://id.boldsystems.org/submission"
    bold_db: str = "public.tax-derep"
    bold_min_identity: float = 0.94
    bold_batch_size: int = 25
    bold_timeout: int = 120

    # NCBI GenBank QBLAST settings
    ncbi_program: str = "blastn"
    ncbi_database: str = "nt"
    ncbi_entrez_query: str = "txid36668[Organism:exp]"  # Default: Formicidae
    ncbi_batch_size: int = 5
    ncbi_timeout: int = 150
    ncbi_email: Optional[str] = None
    ncbi_api_key: Optional[str] = None
    megablast: bool = True

    # Local BLASTn settings
    local_blast_db: Optional[Path] = None

    # GBIF API settings
    gbif_species_match_url: str = "https://api.gbif.org/v1/species/match"

    # Concordance & QC thresholds
    species_identity_threshold: float = 98.0
    genus_identity_threshold: float = 95.0
    low_identity_threshold: float = 90.0

    # Morphospecies prefix mappings
    custom_prefix_map: Dict[str, str] = field(default_factory=dict)
