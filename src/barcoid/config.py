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

    # High-volume execution and safety limits
    max_sequences: Optional[int] = None  # None = process all, int = cap input
    request_delay: float = 2.0  # Default delay (seconds) between remote network batches
    max_retries: int = 3  # Maximum retry attempts on network error / 429
    backoff_factor: float = 2.0  # Exponential backoff factor (seconds)
    dry_run: bool = False  # If True, inspect cache and plan queries without network calls
    force_refresh: bool = False  # If True, bypass cache and re-query external APIs

    # BOLD Systems v5 API settings
    bold_api_url: str = "https://id.boldsystems.org/submission"
    bold_db: str = "public.tax-derep"
    bold_min_identity: float = 0.94
    bold_batch_size: int = 25
    bold_timeout: int = 120
    bold_delay_between_batches: float = 1.5

    # NCBI GenBank QBLAST settings
    ncbi_program: str = "blastn"
    ncbi_database: str = "nt"
    ncbi_entrez_query: str = "txid36668[Organism:exp]"  # Default: Formicidae
    ncbi_batch_size: int = 5
    ncbi_timeout: int = 150
    ncbi_poll_interval: int = 6
    ncbi_delay_between_batches: float = 3.0  # Compliance delay between QBLAST submissions
    ncbi_email: Optional[str] = None
    ncbi_api_key: Optional[str] = None
    megablast: bool = True
    ncbi_hitlist_size: int = 5

    # Local BLASTn settings (high-throughput alternative)
    local_blast_db: Optional[Path] = None
    local_blast_threads: int = 4

    # GBIF API settings
    gbif_species_match_url: str = "https://api.gbif.org/v1/species/match"
    gbif_delay_between_requests: float = 0.15  # Limit GBIF API to ~6-7 req/s
    gbif_kingdom: str = "Animalia"

    # Concordance & QC thresholds
    species_identity_threshold: float = 98.0
    genus_identity_threshold: float = 95.0
    low_identity_threshold: float = 90.0

    # Morphospecies prefix mappings
    custom_prefix_map: Dict[str, str] = field(default_factory=dict)
