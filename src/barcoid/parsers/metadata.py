"""
Ingestion, previewing, and cross-linking of external tabular metadata (CSV, TSV, XLSX).
"""

import csv
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import load_workbook

from barcoid.parsers.headers import DEFAULT_GENUS_PREFIXES, DEFAULT_KNOWN_GENERA

logger = logging.getLogger("barcoid.parsers.metadata")

# Ignored tokens when extracting a genus name from a morphospecies string
NON_GENUS_TOKENS = {
    "sp",
    "spp",
    "cf",
    "aff",
    "nr",
    "indet",
    "unknown",
    "unidentified",
    "none",
    "na",
    "n/a",
    "null",
}


class MetadataParser:
    """Reads external CSV/TSV/XLSX metadata files, previews tables, and indexes by sample/voucher ID."""

    def __init__(
        self,
        metadata_path: Path,
        sample_col: str = "sample_id",
        morpho_col: str = "field_morphospecies",
        genus_col: Optional[str] = "field_genus",
        custom_prefix_map: Optional[Dict[str, str]] = None,
    ):
        self.metadata_path = Path(metadata_path)
        self.sample_col = sample_col.strip()
        self.morpho_col = morpho_col.strip()
        self.genus_col = genus_col.strip() if genus_col else None
        self.prefix_map = dict(DEFAULT_GENUS_PREFIXES)
        if custom_prefix_map:
            self.prefix_map.update({k.upper(): v for k, v in custom_prefix_map.items()})
        self.records: Dict[str, Dict[str, Any]] = {}
        self._load()

    @staticmethod
    def _read_tabular_rows(metadata_path: Path, max_rows: Optional[int] = None) -> Tuple[List[str], List[Dict[str, str]]]:
        """Reads headers and row dictionaries from CSV, TSV, or XLSX files."""
        path = Path(metadata_path)
        if not path.exists():
            raise FileNotFoundError(f"Metadata file not found: {path}")

        suffix = path.suffix.lower()
        if suffix in [".xlsx", ".xlsm"]:
            wb = load_workbook(filename=path, read_only=True, data_only=True)
            try:
                ws = wb.active
                rows_iter = ws.iter_rows(values_only=True)
                header_row = next(rows_iter, None)
                if not header_row:
                    return [], []
                headers = [
                    str(col).strip() if col is not None and str(col).strip() else f"Column_{i + 1}"
                    for i, col in enumerate(header_row)
                ]
                dict_rows: List[Dict[str, str]] = []
                for idx, raw_vals in enumerate(rows_iter):
                    if max_rows is not None and idx >= max_rows:
                        break
                    if not raw_vals or all(v is None or str(v).strip() == "" for v in raw_vals):
                        continue
                    row_dict: Dict[str, str] = {}
                    for col_idx, col_name in enumerate(headers):
                        val = raw_vals[col_idx] if col_idx < len(raw_vals) else None
                        row_dict[col_name] = "" if val is None else str(val).strip()
                    dict_rows.append(row_dict)
                return headers, dict_rows
            finally:
                wb.close()

        delimiter = "\t" if suffix in [".tsv", ".tab"] else ","
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            sample_text = f.read(4096)
            f.seek(0)
            if suffix not in [".tsv", ".tab", ".csv"] and "\t" in sample_text and "," not in sample_text:
                delimiter = "\t"
            reader = csv.DictReader(f, delimiter=delimiter)
            headers = [h.strip() for h in (reader.fieldnames or []) if h is not None]
            dict_rows = []
            for idx, row in enumerate(reader):
                if max_rows is not None and idx >= max_rows:
                    break
                clean_row = {
                    k.strip(): (v.strip() if isinstance(v, str) else "")
                    for k, v in row.items()
                    if k is not None
                }
                if any(clean_row.values()):
                    dict_rows.append(clean_row)
            return headers, dict_rows

    @classmethod
    def read_preview(cls, metadata_path: Path, max_rows: int = 25) -> Tuple[List[str], List[List[str]]]:
        """
        Reads column headers and up to `max_rows` rows as lists of strings for GUI table preview.
        """
        headers, dict_rows = cls._read_tabular_rows(metadata_path, max_rows=max_rows)
        matrix = [[row.get(col, "") for col in headers] for row in dict_rows]
        return headers, matrix

    @staticmethod
    def guess_columns(columns: List[str]) -> Tuple[str, str]:
        """
        Heuristically selects the best candidate columns for (sample_col, morpho_col)
        from a list of spreadsheet column headers.
        """
        if not columns:
            return "sample_id", "field_morphospecies"

        sample_candidates = [
            "sample_id",
            "sampleid",
            "sample",
            "voucher_id",
            "voucher_code",
            "voucher",
            "specimen_id",
            "specimen",
            "processid",
            "id",
            "code",
        ]
        morpho_candidates = [
            "field_morphospecies",
            "morphospecies",
            "morpho_species",
            "morpho",
            "species",
            "taxon",
            "scientific_name",
            "identification",
            "field_id",
            "field_genus",
            "genus",
        ]

        lower_map = {col.lower().strip(): col for col in columns}
        chosen_sample = ""
        for cand in sample_candidates:
            if cand in lower_map:
                chosen_sample = lower_map[cand]
                break
        if not chosen_sample:
            for col in columns:
                if any(k in col.lower() for k in ("sample", "voucher", "specimen", "id")):
                    chosen_sample = col
                    break
        if not chosen_sample:
            chosen_sample = columns[0]

        chosen_morpho = ""
        for cand in morpho_candidates:
            if cand in lower_map and lower_map[cand] != chosen_sample:
                chosen_morpho = lower_map[cand]
                break
        if not chosen_morpho:
            for col in columns:
                if col != chosen_sample and any(
                    k in col.lower() for k in ("morpho", "species", "taxon", "genus", "name", "ident")
                ):
                    chosen_morpho = col
                    break
        if not chosen_morpho:
            chosen_morpho = columns[1] if len(columns) > 1 else columns[0]

        return chosen_sample, chosen_morpho

    def infer_genus_from_morpho(self, morpho_value: str) -> str:
        """
        Extracts or maps a taxonomic genus from a morphospecies code or scientific name string.
        Handles:
          - Prefix codes (e.g. 'PHEI01' -> 'Pheidole', 'CAMP_02' -> 'Camponotus')
          - Binomials / morphospecies strings (e.g. 'Camponotus ligniperda' -> 'Camponotus',
            'Pheidole sp. 1' -> 'Pheidole', 'Formica_rufa' -> 'Formica')
        """
        if not morpho_value:
            return ""
        raw = morpho_value.strip()
        if not raw or raw == "__" or raw.lower() in NON_GENUS_TOKENS:
            return ""

        # 1. Check prefix code pattern e.g. PHEI01 or PHEI-01 or CAMP_02
        m_code = re.match(r"^([A-Za-z]{3,5})[\-\_]?\d+[A-Za-z0-9]*$", raw)
        if m_code:
            prefix = m_code.group(1).upper()
            if prefix in self.prefix_map:
                return self.prefix_map[prefix]

        # 2. Split into tokens by whitespace, underscore, slash, or semicolon
        tokens = [t.strip(".,;()[]") for t in re.split(r"[\s\_\/]+", raw) if t.strip(".,;()[]")]
        for token in tokens:
            low = token.lower()
            if low in NON_GENUS_TOKENS:
                continue
            for known in DEFAULT_KNOWN_GENERA:
                if low == known.lower():
                    return known
            # Check prefix code inside token
            m_tok_code = re.match(r"^([A-Za-z]{3,5})\d+$", token)
            if m_tok_code and m_tok_code.group(1).upper() in self.prefix_map:
                return self.prefix_map[m_tok_code.group(1).upper()]
            # Standard alphabetic genus token (at least 3 letters, no digits)
            if re.match(r"^[A-Za-z]{3,}$", token):
                return token.capitalize()

        return ""

    def _load(self):
        _, rows = self._read_tabular_rows(self.metadata_path)
        for row in rows:
            sample_id = row.get(self.sample_col)
            if sample_id:
                clean_id = sample_id.strip()
                morpho_val = row.get(self.morpho_col, "").strip()
                explicit_genus = (
                    row.get(self.genus_col, "").strip()
                    if self.genus_col and self.genus_col in row
                    else ""
                )
                inferred_genus = explicit_genus or self.infer_genus_from_morpho(morpho_val)
                self.records[clean_id] = {
                    "field_morpho_code": morpho_val,
                    "field_inferred_genus": inferred_genus,
                    "raw_row": row,
                }

        logger.info(f"Loaded {len(self.records)} metadata record(s) from {self.metadata_path.name}")

    def get_metadata(self, sample_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves external metadata dictionary for a given sample/voucher ID."""
        clean = sample_id.strip()
        if clean in self.records:
            return self.records[clean]
        # Also allow matching against base sample token if header has extra suffix
        base_token = clean.split("_")[0]
        return self.records.get(base_token)
