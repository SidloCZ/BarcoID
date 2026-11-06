"""
Markdown audit summary report generator for BarcoID.
"""

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


class ReportExporter:
    """Generates Markdown summary reports of BarcoID identification runs."""

    @staticmethod
    def export(rows: List[Dict[str, Any]], output_path: Path):
        """Generates a structured Markdown report."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        total = len(rows)
        concordance_counts = Counter(r.get("concordance_status", "UNKNOWN") for r in rows)
        qc_counts = Counter(r.get("qc_flag", "UNKNOWN") for r in rows)

        lines = [
            "# BarcoID Identification & QC Audit Report",
            "",
            f"**Total Barcodes Analyzed:** {total}",
            "",
            "## 1. Concordance Breakdown",
            "",
            "| Concordance Status | Count | Percentage |",
            "| :--- | :--- | :--- |",
        ]

        for status in ["CONCORDANT", "NEW_ASSIGNMENT", "MISMATCH_ALERT", "NO_MATCH"]:
            cnt = concordance_counts.get(status, 0)
            pct = (cnt / total * 100.0) if total > 0 else 0.0
            lines.append(f"| **`{status}`** | {cnt} | {pct:.1f}% |")

        lines.extend([
            "",
            "## 2. Quality Control & Discrepancy Flags",
            "",
            "| QC Flag | Count | Interpretation |",
            "| :--- | :--- | :--- |",
        ])

        flag_meanings = {
            "OK": "Consistent authentic barcode",
            "CONTAMINATION_HUMAN": "Homo sapiens contamination detected (>=98% id)",
            "CONTAMINATION_SUSPECT": "Potential cross-well swap or non-target contaminant",
            "DATABASE_CONFLICT": "Taxonomic dispute between BOLD and GenBank",
            "LOW_IDENTITY": "Identity below 90% threshold",
            "LOW_IDENTITY_MISMATCH": "Discrepancy at lower identity",
            "NO_DATA": "No database matches found",
        }

        for flag, cnt in qc_counts.most_common():
            meaning = flag_meanings.get(flag, "Flagged event")
            lines.append(f"| **`{flag}`** | {cnt} | {meaning} |")

        # Discrepancy highlights
        alerts = [r for r in rows if r.get("concordance_status") == "MISMATCH_ALERT" or r.get("qc_flag") != "OK"]
        if alerts:
            lines.extend([
                "",
                "## 3. Flagged Specimens (Discrepancy Highlights)",
                "",
                "| Sample ID | Field ID | BOLD Match | NCBI Match | QC Flag |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ])
            for a in alerts[:50]:  # Top 50 highlights
                meta = a.get("meta", {})
                bold = a.get("bold", {})
                ncbi = a.get("ncbi", {})
                lines.append(
                    f"| {meta.get('sample_id', '')} | {meta.get('field_morpho_code', '')} | "
                    f"{bold.get('top_species', '')} ({bold.get('top_pct_identity', 0.0)}%) | "
                    f"{ncbi.get('top_species', '')} ({ncbi.get('top_pct_identity', 0.0)}%) | "
                    f"**`{a.get('qc_flag', '')}`** |"
                )

        lines.append("")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
