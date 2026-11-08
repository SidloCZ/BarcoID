"""
Multi-tab, styled Excel exporter for BarcoID.
"""

from pathlib import Path
from typing import Any, Dict, List

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


class ExcelExporter:
    """Exports BarcoID identification matrices to stylized Excel workbooks."""

    @staticmethod
    def export(rows: List[Dict[str, Any]], output_path: Path):
        """Generates a 4-tab formatted Excel workbook."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        wb = openpyxl.Workbook()

        # Sheet 1: Master 4-way comparison
        ws_comp = wb.active
        ws_comp.title = "Taxonomic_Comparison"

        # Sheet 2: BOLD detailed hits
        ws_bold = wb.create_sheet(title="BOLD_Detailed_Hits")

        # Sheet 3: NCBI detailed hits
        ws_ncbi = wb.create_sheet(title="NCBI_Detailed_Hits")

        # Sheet 4: Discrepancies and QC
        ws_qc = wb.create_sheet(title="Discrepancies_and_QC")

        # Styles
        font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_white_bold = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_dark_bold = Font(name="Calibri", size=11, bold=True, color="111111")
        fill_header = PatternFill(start_color="4C9E45", end_color="4C9E45", fill_type="solid")
        fill_qc_header = PatternFill(start_color="111111", end_color="111111", fill_type="solid")
        fill_green = PatternFill(start_color="4C9E45", end_color="4C9E45", fill_type="solid")
        fill_green_tint = PatternFill(start_color="EAF4E9", end_color="EAF4E9", fill_type="solid")
        fill_alert = PatternFill(start_color="FDECEC", end_color="FDECEC", fill_type="solid")
        align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        align_left = Alignment(horizontal="left", vertical="center")
        border_thin = Border(
            left=Side(style="thin", color="D9D9D9"),
            right=Side(style="thin", color="D9D9D9"),
            top=Side(style="thin", color="D9D9D9"),
            bottom=Side(style="thin", color="D9D9D9"),
        )

        comp_headers = [
            "Sample_ID", "Plate", "Seq_Len_bp", "Read_Coverage", "Ambiguities",
            "Field_Locality", "Field_Morpho_Code", "Field_Inferred_Genus", "Field_Voucher",
            "BOLD_Top_Taxon", "BOLD_Genus", "BOLD_Pct_Identity", "BOLD_BIN_URI", "BOLD_Process_ID",
            "NCBI_Top_Taxon", "NCBI_Genus", "NCBI_Pct_Identity", "NCBI_Accession", "NCBI_Evalue",
            "GBIF_Canonical_Name", "GBIF_Rank", "GBIF_Confidence", "GBIF_Status", "GBIF_Taxon_ID",
            "Consensus_Genus", "Consensus_Species", "Concordance_Status", "QC_Flag", "Full_FASTA_Header"
        ]

        ws_comp.append(comp_headers)
        ws_qc.append(comp_headers)

        bold_headers = [
            "sample_id", "phylum", "class", "order", "family", "genus", "species",
            "pct_identity", "status", "BIN", "process_id", "bitscore", "overlap", "mismatch", "evalue"
        ]
        ws_bold.append(bold_headers)

        ncbi_headers = [
            "sample_id", "accession", "genus", "species", "pct_identity", "align_length", "bitscore", "evalue", "title"
        ]
        ws_ncbi.append(ncbi_headers)

        for r in rows:
            meta = r.get("meta", {})
            bold = r.get("bold", {})
            ncbi = r.get("ncbi", {})
            gbif = r.get("gbif", {})

            comp_row = [
                meta.get("sample_id", ""),
                meta.get("plate", ""),
                meta.get("seq_length", 0),
                meta.get("coverage", 0),
                meta.get("ambiguities", 0),
                meta.get("locality", ""),
                meta.get("field_morpho_code", ""),
                meta.get("field_inferred_genus", ""),
                meta.get("voucher_code", ""),
                bold.get("top_species") or bold.get("top_genus") or "",
                bold.get("top_genus", ""),
                bold.get("top_pct_identity", 0.0),
                bold.get("top_bin", ""),
                bold.get("top_process_id", ""),
                ncbi.get("top_species") or ncbi.get("top_genus") or "",
                ncbi.get("top_genus", ""),
                ncbi.get("top_pct_identity", 0.0),
                ncbi.get("top_accession", ""),
                str(ncbi.get("top_evalue", "") or ""),
                gbif.get("canonicalName", ""),
                gbif.get("rank", ""),
                gbif.get("confidence", 0),
                gbif.get("status", ""),
                str(gbif.get("usageKey", "") or ""),
                r.get("consensus_genus", ""),
                r.get("consensus_species", ""),
                r.get("concordance_status", ""),
                r.get("qc_flag", ""),
                meta.get("full_header", ""),
            ]
            ws_comp.append(comp_row)

            if r.get("concordance_status") == "MISMATCH_ALERT" or r.get("qc_flag") != "OK":
                ws_qc.append(comp_row)

            for bh in bold.get("all_hits", []):
                ws_bold.append([
                    meta.get("sample_id", ""),
                    bh.get("phylum", ""),
                    bh.get("class", ""),
                    bh.get("order", ""),
                    bh.get("family", ""),
                    bh.get("genus", ""),
                    bh.get("species", ""),
                    bh.get("pct_identity", 0.0),
                    "public",
                    bh.get("bin_uri", ""),
                    bh.get("process_id", ""),
                    bh.get("bitscore", 0),
                    bh.get("overlap", 0),
                    bh.get("mismatch", 0),
                    str(bh.get("evalue", "") or ""),
                ])

            for nh in ncbi.get("all_hits", []):
                ws_ncbi.append([
                    meta.get("sample_id", ""),
                    nh.get("accession", ""),
                    nh.get("genus", ""),
                    nh.get("species", ""),
                    nh.get("pct_identity", 0.0),
                    nh.get("alignment_length", 0),
                    nh.get("bitscore", 0.0),
                    str(nh.get("evalue", "") or ""),
                    nh.get("title", ""),
                ])

        # Formatting sheets
        for ws, is_qc in [(ws_comp, False), (ws_qc, True), (ws_bold, False), (ws_ncbi, False)]:
            ws.freeze_panes = "A2"
            for col_idx in range(1, ws.max_column + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.font = font_header
                cell.fill = fill_qc_header if is_qc else fill_header
                cell.alignment = align_center

            for col in ws.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    cell.border = border_thin
                    val_str = str(cell.value or "")
                    if cell.row > 1 and cell.column not in (3, 4, 5, 12, 17, 22):
                        cell.alignment = align_left
                    if cell.row > 1 and ws in (ws_comp, ws_qc) and cell.column in (27, 28):
                        if val_str in ("CONCORDANT", "OK"):
                            cell.fill = fill_green
                            cell.font = font_white_bold
                        elif val_str == "NEW_ASSIGNMENT":
                            cell.fill = fill_green_tint
                            cell.font = font_dark_bold
                        elif val_str and val_str != "NO_MATCH":
                            cell.fill = fill_alert
                            cell.font = font_dark_bold
                    if len(val_str) > max_len:
                        max_len = len(val_str)
                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 10), 45)

        wb.save(output_path)

