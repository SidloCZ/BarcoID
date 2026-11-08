"""
Tabular TSV and CSV exporters for bioinformatics pipelines.
"""

import csv
from pathlib import Path
from typing import Any, Dict, List


class TabularExporter:
    """Exports identification rows to clean CSV or TSV files."""

    @staticmethod
    def export(rows: List[Dict[str, Any]], output_path: Path, delimiter: str = "\t"):
        """Exports rows to a tabular flat file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "sample_id",
            "plate",
            "seq_length",
            "coverage",
            "ambiguities",
            "field_locality",
            "field_morpho_code",
            "field_inferred_genus",
            "field_voucher",
            "bold_genus",
            "bold_species",
            "bold_pct_identity",
            "bold_bin",
            "bold_process_id",
            "ncbi_genus",
            "ncbi_species",
            "ncbi_pct_identity",
            "ncbi_accession",
            "ncbi_evalue",
            "gbif_canonical_name",
            "gbif_status",
            "consensus_genus",
            "consensus_species",
            "concordance_status",
            "qc_flag",
        ]

        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=delimiter)
            writer.writeheader()

            for r in rows:
                meta = r.get("meta", {})
                bold = r.get("bold", {})
                ncbi = r.get("ncbi", {})
                gbif = r.get("gbif", {})

                writer.writerow(
                    {
                        "sample_id": meta.get("sample_id", ""),
                        "plate": meta.get("plate", ""),
                        "seq_length": meta.get("seq_length", 0),
                        "coverage": meta.get("coverage", 0),
                        "ambiguities": meta.get("ambiguities", 0),
                        "field_locality": meta.get("locality", ""),
                        "field_morpho_code": meta.get("field_morpho_code", ""),
                        "field_inferred_genus": meta.get("field_inferred_genus", ""),
                        "field_voucher": meta.get("voucher_code", ""),
                        "bold_genus": bold.get("top_genus", ""),
                        "bold_species": bold.get("top_species", ""),
                        "bold_pct_identity": bold.get("top_pct_identity", 0.0),
                        "bold_bin": bold.get("top_bin", ""),
                        "bold_process_id": bold.get("top_process_id", ""),
                        "ncbi_genus": ncbi.get("top_genus", ""),
                        "ncbi_species": ncbi.get("top_species", ""),
                        "ncbi_pct_identity": ncbi.get("top_pct_identity", 0.0),
                        "ncbi_accession": ncbi.get("top_accession", ""),
                        "ncbi_evalue": ncbi.get("top_evalue", ""),
                        "gbif_canonical_name": gbif.get("canonicalName", ""),
                        "gbif_status": gbif.get("status", ""),
                        "consensus_genus": r.get("consensus_genus", ""),
                        "consensus_species": r.get("consensus_species", ""),
                        "concordance_status": r.get("concordance_status", ""),
                        "qc_flag": r.get("qc_flag", ""),
                    }
                )
