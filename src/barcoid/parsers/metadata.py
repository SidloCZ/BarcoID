"""
Ingestion and cross-linking of external tabular metadata (CSV/TSV).
"""

import csv
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("barcoid.parsers.metadata")


class MetadataParser:
    """Reads external CSV/TSV metadata files and indexes by sample or voucher ID."""

    def __init__(
        self,
        metadata_path: Path,
        sample_col: str = "sample_id",
        morpho_col: str = "field_morphospecies",
        genus_col: Optional[str] = "field_genus",
    ):
        self.metadata_path = Path(metadata_path)
        self.sample_col = sample_col.strip()
        self.morpho_col = morpho_col.strip()
        self.genus_col = genus_col.strip() if genus_col else None
        self.records: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        if not self.metadata_path.exists():
            raise FileNotFoundError(f"Metadata file not found: {self.metadata_path}")

        delimiter = "\t" if self.metadata_path.suffix.lower() in [".tsv", ".tab"] else ","
        with open(self.metadata_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                sample_id = row.get(self.sample_col)
                if sample_id:
                    clean_id = sample_id.strip()
                    self.records[clean_id] = {
                        "field_morpho_code": row.get(self.morpho_col, "").strip(),
                        "field_inferred_genus": row.get(self.genus_col, "").strip() if self.genus_col else "",
                        "raw_row": row,
                    }

        logger.info(f"Loaded {len(self.records)} metadata record(s) from {self.metadata_path.name}")

    def get_metadata(self, sample_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves external metadata dictionary for a given sample/voucher ID."""
        return self.records.get(sample_id.strip())
