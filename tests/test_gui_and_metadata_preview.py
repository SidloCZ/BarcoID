"""
Unit and integration tests for the standalone Desktop GUI, interactive metadata table preview,
automatic morphospecies-to-genus resolution, and dual CLI/GUI launcher.
"""

import tkinter as tk
from pathlib import Path

import pytest
from openpyxl import Workbook

from barcoid.cli import main
from barcoid.config import BarcoIDConfig
from barcoid.gui import (
    PALETTE,
    SVG_ICON_PATH,
    BarcoIDApp,
    build_config_from_inputs,
    get_cell_highlight,
)
from barcoid.parsers.metadata import MetadataParser
from barcoid.pipeline import BarcoIDPipeline


def test_single_cell_highlighting_rules():
    """Verifies that only Concordance_Status and QC_Flag cells receive highlight fills."""
    assert get_cell_highlight("Sample_ID", "MJB001") == ("#FFFFFF", "#111111", False)
    assert get_cell_highlight("Concordance_Status", "CONCORDANT") == ("#4C9E45", "#FFFFFF", True)
    assert get_cell_highlight("Concordance_Status", "NEW_ASSIGNMENT") == ("#EAF4E9", "#111111", True)
    assert get_cell_highlight("Concordance_Status", "MISMATCH_ALERT") == ("#FDECEC", "#111111", True)
    assert get_cell_highlight("QC_Flag", "OK") == ("#4C9E45", "#FFFFFF", True)
    assert get_cell_highlight("QC_Flag", "CONTAMINATION_SUSPECT") == ("#FDECEC", "#111111", True)


def test_palette_and_4streams_svg():
    """Verifies the 2-color minimalist palette (#4C9E45 + #111111/#FFFFFF) and 4-streams SVG icon."""
    assert PALETTE["primary"] == "#4C9E45"
    assert PALETTE["text_dark"] == "#111111"
    assert PALETTE["bg_canvas"] == "#FFFFFF"
    assert SVG_ICON_PATH.exists()
    svg_content = SVG_ICON_PATH.read_text(encoding="utf-8")
    assert "<svg" in svg_content
    assert "#4C9E45" in svg_content


def test_metadata_preview_csv_and_xlsx(tmp_path: Path):
    """Tests reading tabular previews from both CSV and Excel (.xlsx) metadata files."""
    csv_path = tmp_path / "vouchers.csv"
    csv_path.write_text(
        "Voucher_ID,Locality,Morphospecies_Name\n"
        "MJB001,Madagascar,Camponotus maculatus\n"
        "MJB002,Madagascar,PHEI04\n",
        encoding="utf-8",
    )

    headers, rows = MetadataParser.read_preview(csv_path, max_rows=10)
    assert headers == ["Voucher_ID", "Locality", "Morphospecies_Name"]
    assert len(rows) == 2
    assert rows[0] == ["MJB001", "Madagascar", "Camponotus maculatus"]

    sample_col, morpho_col = MetadataParser.guess_columns(headers)
    assert sample_col == "Voucher_ID"
    assert morpho_col == "Morphospecies_Name"

    # Also test Excel (.xlsx) metadata preview and parsing without a separate genus column
    xlsx_path = tmp_path / "vouchers.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["SpecimenCode", "Site", "MorphoDetermination"])
    ws.append(["MJB0001426_MJB016_redo3", "Valavahalo", "Pheidole sp. 12"])
    ws.append(["MJB0001457_MJB016_redo3", "Valavahalo", "TECH01"])
    wb.save(xlsx_path)

    x_headers, x_rows = MetadataParser.read_preview(xlsx_path)
    assert x_headers == ["SpecimenCode", "Site", "MorphoDetermination"]
    assert len(x_rows) == 2

    parser = MetadataParser(
        xlsx_path,
        sample_col="SpecimenCode",
        morpho_col="MorphoDetermination",
        genus_col=None,
    )
    rec1 = parser.get_metadata("MJB0001426_MJB016_redo3")
    assert rec1 is not None
    assert rec1["field_morpho_code"] == "Pheidole sp. 12"
    assert rec1["field_inferred_genus"] == "Pheidole"

    rec2 = parser.get_metadata("MJB0001457_MJB016_redo3")
    assert rec2 is not None
    assert rec2["field_morpho_code"] == "TECH01"
    assert rec2["field_inferred_genus"] == "Technomyrmex"


def test_cli_launches_gui_when_no_arguments(mocker):
    """Ensures double-clicking the executable (no args) or passing --gui launches the GUI."""
    mock_gui = mocker.patch("barcoid.gui.launch_gui")
    main([])
    mock_gui.assert_called_once()

    mock_gui.reset_mock()
    main(["--gui"])
    mock_gui.assert_called_once()


def test_build_config_from_inputs(tmp_path: Path):
    """Verifies GUI form inputs map accurately to BarcoIDConfig."""
    fasta = tmp_path / "test.fasta"
    fasta.write_text(">seq1\nACGT\n", encoding="utf-8")

    cfg = build_config_from_inputs(
        fasta_path=fasta,
        output_dir=None,
        taxon="Insecta",
        max_sequences_str="25",
        ncbi_email="user@example.org",
        ncbi_api_key="KEY123",
        dry_run=True,
        force_refresh=True,
    )
    assert cfg.output_dir == tmp_path / "results"
    assert cfg.cache_dir == tmp_path / ".id_cache"
    assert cfg.ncbi_entrez_query == "Insecta[Organism:exp]"
    assert cfg.max_sequences == 25
    assert cfg.ncbi_email == "user@example.org"
    assert cfg.ncbi_api_key == "KEY123"
    assert cfg.dry_run is True
    assert cfg.force_refresh is True


def test_pipeline_progress_callback(tmp_path: Path):
    """Verifies that BarcoIDPipeline emits stage progress updates for the GUI progress bar."""
    fasta = tmp_path / "sample.fasta"
    fasta.write_text(">MJB0001426_MJB016_redo3\nACGTACGTACGT\n", encoding="utf-8")

    cfg = BarcoIDConfig(
        cache_dir=tmp_path / ".id_cache",
        output_dir=tmp_path / "results",
        dry_run=True,
    )
    pipeline = BarcoIDPipeline(cfg)

    events = []
    pipeline.run(
        fasta_path=fasta,
        progress_callback=lambda stage, pct: events.append((stage, pct)),
    )
    assert len(events) >= 2
    assert events[0][1] == 10.0
    assert events[-1][1] == 100.0


def test_gui_interactive_column_picker():
    """Tests loading sample_metadata.csv into BarcoIDApp and clicking a column header."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip("No Tcl/Tk display available in headless environment")

    try:
        app = BarcoIDApp(root)
        assert app.current_step == 0

        # Click through wizard steps: Step 0 -> Step 1 -> Step 2
        app.show_step(1)
        assert app.current_step == 1

        sample_meta = Path(__file__).resolve().parent.parent / "examples" / "sample_metadata.csv"
        app.load_metadata_file(sample_meta)

        assert "field_morphospecies" in app.meta_columns
        assert app.morpho_col_var.get() == "field_morphospecies"
        assert "Inferred Genus: Pheidole" in app.morpho_preview_var.get()

        # Simulate clicking the 'field_genus' column header to switch the morphospecies column
        app.on_column_header_clicked("field_genus")
        assert app.morpho_col_var.get() == "field_genus"
        heading_text = app.meta_tree.heading("field_genus", "text")
        assert "[MORPHOSPECIES]" in heading_text

        app.show_step(2)
        assert app.current_step == 2
        assert "field_genus" in app.run_overview_var.get()

        # Verify active circle spinner animation and Done state on stream cards
        app._set_service_states(ncbi="Active", bold="Done")
        app._animate_spinners()
        assert len(app.service_spinners["ncbi"].find_all()) >= 2
        assert len(app.service_spinners["bold"].find_all()) >= 2

        # Step 4: Results table with single-cell highlighting
        assert len(app.step_frames) == 4
        app.populate_results_table(
            [
                {
                    "meta": {
                        "sample_id": "MJB0001426",
                        "field_morpho_code": "PHEI01",
                        "field_inferred_genus": "Pheidole",
                    },
                    "bold": {"top_species": "Pheidole megacephala", "top_pct_identity": 99.4},
                    "ncbi": {"top_species": "Pheidole megacephala", "top_pct_identity": 99.2},
                    "gbif": {"canonicalName": "Pheidole megacephala"},
                    "consensus_species": "Pheidole megacephala",
                    "concordance_status": "CONCORDANT",
                    "qc_flag": "OK",
                }
            ]
        )
        app.show_step(3)
        assert app.current_step == 3
        assert len(app.results_canvas.find_all()) > 20

        # Verify default widths: Sample_ID (idx 0) and Consensus_Species (idx 8) are expanded,
        # while intermediate column BOLD_Taxon (idx 3) starts squished, and double-click expands it
        assert app.results_col_widths[0] >= 180
        assert app.results_col_widths[8] >= 180
        squished_bold_w = app.results_col_widths[3]
        assert squished_bold_w < 110
        app.auto_expand_results_column(3)
        assert app.results_col_widths[3] > squished_bold_w
        # Double-clicking an already expanded intermediate column squishes it back
        app.auto_expand_results_column(3)
        assert app.results_col_widths[3] == squished_bold_w

        # Verify Ctrl+Shift+D diagnostic terminal toggle and bug report builder
        assert app.terminal_win is None
        app.toggle_terminal_window()
        assert app.terminal_win is not None
        diag_text = app.build_diagnostic_report_text(include_api_ping=False)
        assert "BarcoID Diagnostic & Bug Report" in diag_text
        app.toggle_terminal_window()
        assert app.terminal_win is None
    finally:
        root.destroy()

