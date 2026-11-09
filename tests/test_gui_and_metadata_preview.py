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
    ICO_ICON_PATH,
    PALETTE,
    PNG_ICON_PATH,
    SVG_ARROW_LEFT_PATH,
    SVG_ARROW_RIGHT_PATH,
    SVG_BUG_PATH,
    SVG_CHECK_CIRCLE_PATH,
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
    assert get_cell_highlight("Concordance_Status", "NEW_ASSIGNMENT") == (
        "#EAF4E9",
        "#111111",
        True,
    )
    assert get_cell_highlight("Concordance_Status", "MISMATCH_ALERT") == (
        "#FDECEC",
        "#111111",
        True,
    )
    assert get_cell_highlight("QC_Flag", "OK") == ("#4C9E45", "#FFFFFF", True)
    assert get_cell_highlight("QC_Flag", "CONTAMINATION_SUSPECT") == ("#FDECEC", "#111111", True)
    assert get_cell_highlight("NCBI_Taxon", "FAILED (Timeout)") == ("#FFF9C4", "#7A5200", True)
    assert get_cell_highlight("BOLD_Taxon", "FAILED (API Error)") == ("#FFF9C4", "#7A5200", True)


def test_palette_and_4streams_svg():
    """Verifies the 2-color minimalist palette, logo.svg, and icon assets."""
    assert PALETTE["primary"] == "#4C9E45"
    assert PALETTE["text_dark"] == "#111111"
    assert PALETTE["bg_canvas"] == "#FFFFFF"
    assert SVG_ICON_PATH.exists()
    assert PNG_ICON_PATH.exists()
    assert ICO_ICON_PATH.exists()
    for svg_path in (
        SVG_ICON_PATH,
        SVG_ARROW_RIGHT_PATH,
        SVG_ARROW_LEFT_PATH,
        SVG_CHECK_CIRCLE_PATH,
        SVG_BUG_PATH,
    ):
        assert svg_path.exists()
        svg_content = svg_path.read_text(encoding="utf-8")
        assert "<svg" in svg_content


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

        # Verify active circle spinner animation and smooth SVG Done state on stream cards
        app._set_service_states(ncbi="Active", bold="Done")
        app._animate_spinners()
        assert len(app.service_spinners["ncbi"].find_all()) == 1
        assert len(app.service_spinners["bold"].find_all()) == 1
        assert len(app.spinner_photos) == 15
        assert app.icon_check_done is not None
        assert app.icon_arrow_right is not None
        assert app.icon_arrow_left is not None
        assert app.icon_radio_unselected is not None
        assert app.icon_radio_selected is not None
        assert app.icon_check_unselected is not None
        assert app.icon_check_selected is not None
        assert app.icon_help is not None
        assert app.help_btn is not None
        assert app.author_tag is not None
        assert app.author_tag.cget("text") == "Made by SidloCZ"
        assert app.author_tag.cget("fg") == "#888888"
        assert len(app._app_icon_refs) >= 1

        # Step 4: Results table with single-cell highlighting & segmented summary cards
        assert len(app.step_frames) == 4
        assert set(app.summary_cards.keys()) == {
            "TOTAL",
            "CONCORDANT",
            "NEW_ASSIGNMENT",
            "MISMATCH_ALERT",
            "NO_MATCH",
        }
        app._update_summary_cards(
            total=3,
            counts={
                "CONCORDANT": 2,
                "NEW_ASSIGNMENT": 1,
                "MISMATCH_ALERT": 0,
                "NO_MATCH": 0,
            },
        )
        assert app.summary_card_vars["TOTAL"].get() == "3"
        assert app.summary_card_vars["CONCORDANT"].get() == "2"
        assert app.summary_card_vars["NEW_ASSIGNMENT"].get() == "1"
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

        # Verify User Guide and App Info Window opens, renders, and has section jump buttons
        assert app.guide_win is None
        app.open_guide_window()
        assert app.guide_win is not None
        assert "User Guide and App info" in app.guide_win.title()
        assert len(app.guide_win._guide_photos) == 4
        assert any("Data Privacy" in step[0] for step in app.guide_win._guide_steps)
        app.guide_win.destroy()
        app.guide_win = None
    finally:
        root.destroy()


def test_on_close_window_warning(monkeypatch):
    """Verifies that closing the window prompts confirmation if a run is actively executing."""
    root = tk.Tk()
    root.withdraw()
    try:
        app = BarcoIDApp(root)
        app.is_running = True

        prompt_called = []

        def mock_askyesno(title, msg, **kwargs):
            prompt_called.append((title, msg))
            return False  # User clicks 'No' to abort closing

        monkeypatch.setattr("tkinter.messagebox.askyesno", mock_askyesno)
        app._on_close_window()
        assert len(prompt_called) == 1
        assert "Run in Progress" in prompt_called[0][0]
        assert root.winfo_exists()

        # When user clicks 'Yes', window is destroyed
        monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *args, **kwargs: True)
        app._on_close_window()
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_bug_svg_button_and_report_issue(monkeypatch):
    """Verifies that the bug SVG icon opens diagnostics and 'Report issue' opens GitHub with prefilled data."""
    root = tk.Tk()
    root.withdraw()
    try:
        app = BarcoIDApp(root)

        # 1. Verify bug_btn exists and opens diagnostic window
        assert hasattr(app, "bug_btn")
        assert app.terminal_win is None
        app.bug_btn.invoke()
        assert app.terminal_win is not None
        assert app.terminal_win.winfo_exists()

        # 2. Mock webbrowser and clipboard to test 'Report issue'
        opened_urls = []

        def mock_open_tab(url):
            opened_urls.append(url)

        monkeypatch.setattr("webbrowser.open_new_tab", mock_open_tab)

        app.last_error_trace = "TypeError: MetadataParser.__init__() got an unexpected keyword argument 'sample_id_col'"
        app.log_history = [
            "16:12:04 [INFO] Loaded 115 sequence(s)",
            "16:12:04 [ERROR] Pipeline execution error: MetadataParser.__init__()",
        ]

        app.report_github_issue()

        assert len(opened_urls) == 1
        issue_url = opened_urls[0]
        assert "https://github.com/SidloCZ/BarcoID/issues/new" in issue_url
        assert "TypeError" in issue_url
        assert "sample_id_col" in issue_url

        # Verify clipboard contents
        clipboard_content = root.clipboard_get()
        assert "BarcoID Diagnostic & Bug Report" in clipboard_content
        assert "TypeError: MetadataParser.__init__()" in clipboard_content

        app.terminal_win.destroy()
        app.terminal_win = None
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_metadata_parser_flexibility_and_aliases(tmp_path: Path):
    """Tests MetadataParser with parameter aliases (sample_id_col, morphospecies_col) and .load() method."""
    xlsx_path = tmp_path / "metadata.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["Sample_ID", "Field_Morpho_Code", "Notes"])
    ws.append(["MJB0001426", "PHEI01", "Rainforest leaf litter"])
    ws.append(["MJB0001427", "Camponotus maculatus", "Tree trunk"])
    wb.save(xlsx_path)

    # 1. Test alias arguments in __init__
    parser1 = MetadataParser(
        metadata_path=xlsx_path,
        sample_id_col="Sample_ID",
        morphospecies_col="Field_Morpho_Code",
    )
    assert len(parser1.records) == 2
    rec1 = parser1.get_metadata("MJB0001426")
    assert rec1 is not None
    assert rec1["field_morpho_code"] == "PHEI01"
    assert rec1["field_inferred_genus"] == "Pheidole"

    # 2. Test case-insensitive and base token matching
    rec1_lower = parser1.get_metadata("mjb0001426")
    assert rec1_lower == rec1
    rec1_suffix = parser1.get_metadata("MJB0001426_MJB016_redo3")
    assert rec1_suffix == rec1

    # 3. Test two-step initialization and .load()
    parser2 = MetadataParser(sample_id_col="Sample_ID", morphospecies_col="Field_Morpho_Code")
    assert len(parser2.records) == 0
    records = parser2.load(xlsx_path)
    assert len(records) == 2
    rec2 = parser2.get_metadata("MJB0001427")
    assert rec2 is not None
    assert rec2["field_inferred_genus"] == "Camponotus"


def test_pipeline_e2e_with_metadata(tmp_path: Path):
    """Tests BarcoIDPipeline execution with external metadata integration."""
    cache_dir = tmp_path / ".id_cache"
    output_dir = tmp_path / "results"

    config = BarcoIDConfig(cache_dir=cache_dir, output_dir=output_dir, skip_ncbi=True)
    pipeline = BarcoIDPipeline(config)

    seq1 = "ATCGATCGATCGATCG"
    pipeline.cache_manager.set_bold(
        seq1,
        {
            "has_match": True,
            "hit_count": 1,
            "top_genus": "Pheidole",
            "top_species": "Pheidole oceanica",
            "top_pct_identity": 99.5,
            "top_bin": "BOLD:AAA1111",
            "top_process_id": "TEST_001",
            "all_hits": [],
        },
    )
    pipeline.cache_manager.set_gbif(
        "Pheidole oceanica",
        {
            "usageKey": 12345,
            "canonicalName": "Pheidole oceanica",
            "rank": "SPECIES",
            "status": "ACCEPTED",
            "confidence": 99,
        },
    )
    pipeline.cache_manager.save()

    fasta_path = tmp_path / "test.fasta"
    fasta_path.write_text(f">SPEC_001_PlateA\n{seq1}\n", encoding="utf-8")

    meta_path = tmp_path / "test_meta.csv"
    meta_path.write_text(
        "Sample_Code,Field_Morpho\nSPEC_001,Pheidole megacephala\n", encoding="utf-8"
    )

    rows = pipeline.run(
        fasta_path=fasta_path,
        metadata_path=meta_path,
        sample_col="Sample_Code",
        morpho_col="Field_Morpho",
    )

    assert len(rows) == 1
    res = rows[0]
    assert res["consensus_genus"] == "Pheidole"
    assert res["meta"]["field_morpho_code"] == "Pheidole megacephala"
    assert res["meta"]["field_inferred_genus"] == "Pheidole"
    assert res["concordance_status"] == "CONCORDANT"


def test_results_sticky_header_and_summary_filtering():
    """Verifies that the results table has a sticky header and summary cards act as interactive filters."""
    root = tk.Tk()
    root.withdraw()
    try:
        app = BarcoIDApp(root)
        app.show_step(3)

        # 1. Sticky Header Structure
        assert hasattr(app, "results_header_canvas")
        assert hasattr(app, "results_canvas")
        assert app.results_header_canvas != app.results_canvas

        test_data = [
            {
                "meta": {"sample_id": f"SMP_{i:03d}"},
                "bold": {"top_species": f"Species {i}", "top_pct_identity": 99.0},
                "ncbi": {"top_species": f"Species {i}", "top_pct_identity": 99.0},
                "gbif": {"canonicalName": f"Species {i}"},
                "consensus_species": f"Species {i}",
                "concordance_status": status,
                "qc_flag": "OK",
            }
            for i, status in enumerate(
                [
                    "CONCORDANT",
                    "CONCORDANT",
                    "NEW_ASSIGNMENT",
                    "MISMATCH_ALERT",
                    "NO_MATCH",
                ]
            )
        ]

        app.populate_results_table(test_data)

        # Total rows = 5, all shown initially
        assert len(app.all_results_matrix) == 5
        assert len(app.results_matrix) == 5
        assert app.summary_card_vars["TOTAL"].get() == "5"
        assert app.summary_card_vars["CONCORDANT"].get() == "2"
        assert app.summary_card_vars["NEW_ASSIGNMENT"].get() == "1"
        assert app.summary_card_vars["MISMATCH_ALERT"].get() == "1"
        assert app.summary_card_vars["NO_MATCH"].get() == "1"

        # 2. Test Sticky Header: Vertical scrolling affects only data canvas
        app.results_canvas.yview_moveto(0.5)
        # Header canvas yview remains at top (0.0)
        assert app.results_header_canvas.yview()[0] == 0.0

        # 3. Test Clicking Summary Filter Cards
        # Click CONCORDANT -> filters to 2 rows
        app.on_summary_card_clicked("CONCORDANT")
        assert len(app.results_matrix) == 2
        assert all(r[9] == "CONCORDANT" for r in app.results_matrix)
        assert app.active_status_filter == "CONCORDANT"
        assert "Showing 2 of 5 (Concordant)" in app.filter_indicator_var.get()
        # Active card styling
        c_card, c_title, c_val = app.summary_cards["CONCORDANT"]
        assert c_card.cget("bg") == PALETTE["primary"]
        assert c_val.cget("fg") == "#FFFFFF"

        # Click CONCORDANT again -> toggles back to TOTAL (shows all 5 rows)
        app.on_summary_card_clicked("CONCORDANT")
        assert len(app.results_matrix) == 5
        assert app.active_status_filter == "TOTAL"
        assert app.filter_indicator_var.get() == ""

        # Click MISMATCH_ALERT -> filters to 1 row
        app.on_summary_card_clicked("MISMATCH_ALERT")
        assert len(app.results_matrix) == 1
        assert app.results_matrix[0][9] == "MISMATCH_ALERT"
        assert app.active_status_filter == "MISMATCH_ALERT"
        m_card, m_title, m_val = app.summary_cards["MISMATCH_ALERT"]
        assert m_card.cget("bg") == "#D32F2F"
        assert m_val.cget("fg") == "#FFFFFF"

        # Click TOTAL card -> resets filter to all 5
        app.on_summary_card_clicked("TOTAL")
        assert len(app.results_matrix) == 5
        assert app.active_status_filter == "TOTAL"
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_failed_results_and_rerun_workflow(tmp_path: Path, monkeypatch):
    """Verifies failed BOLD/NCBI results formatting, yellow cell styling, and Re-run workflow."""
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *args, **kwargs: None)
    monkeypatch.setattr("tkinter.messagebox.showwarning", lambda *args, **kwargs: None)
    monkeypatch.setattr("tkinter.messagebox.showerror", lambda *args, **kwargs: None)
    root = tk.Tk()
    root.withdraw()
    try:
        app = BarcoIDApp(root)
        app.show_step(3)

        # 1. Setup mock results containing 1 failed NCBI lookup and 1 successful
        rows = [
            {
                "meta": {
                    "sample_id": "SMP_001",
                    "full_header": "SMP_001_PlateA",
                    "sequence": "ACGTACGT",
                },
                "bold": {"top_species": "Camponotus ligniperda", "top_pct_identity": 99.2},
                "ncbi": {"failed": True, "error": "Timeout", "status": "NCBI query timed out"},
                "gbif": {"canonicalName": "Camponotus ligniperda"},
                "consensus_species": "Camponotus ligniperda",
                "concordance_status": "CONCORDANT",
                "qc_flag": "OK",
            },
            {
                "meta": {
                    "sample_id": "SMP_002",
                    "full_header": "SMP_002_PlateA",
                    "sequence": "TGCATGCA",
                },
                "bold": {"top_species": "Pheidole megacephala", "top_pct_identity": 98.8},
                "ncbi": {"top_species": "Pheidole megacephala", "top_pct_identity": 99.0},
                "gbif": {"canonicalName": "Pheidole megacephala"},
                "consensus_species": "Pheidole megacephala",
                "concordance_status": "CONCORDANT",
                "qc_flag": "OK",
            },
        ]

        app.populate_results_table(rows)

        # 2. Verify row 0 has FAILED (Timeout) in NCBI_Taxon and row 1 has species
        assert app.results_matrix[0][5] == "FAILED (Timeout)"
        assert app.results_matrix[1][5] == "Pheidole megacephala"

        # 3. Verify cell highlight rules: failed cell returns warning_tint (#FFF9C4)
        bg, fg, bold = get_cell_highlight("NCBI_Taxon", app.results_matrix[0][5])
        assert bg == PALETTE["warning_tint"]
        assert fg == PALETTE["warning_text"]
        assert bold is True

        # 4. Verify Re-run Failed button is enabled with count 1
        assert app._is_row_failed(rows[0]) is True
        assert app._is_row_failed(rows[1]) is False
        assert app.rerun_failed_btn.cget("state") == "normal"
        assert "Re-run Failed (1)" in app.rerun_failed_btn.cget("text")

        # 5. Verify Combine & Overwrite logic
        rerun_resolved = [
            {
                "meta": {
                    "sample_id": "SMP_001",
                    "full_header": "SMP_001_PlateA",
                    "sequence": "ACGTACGT",
                },
                "bold": {"top_species": "Camponotus ligniperda", "top_pct_identity": 99.2},
                "ncbi": {"top_species": "Camponotus ligniperda", "top_pct_identity": 99.5},
                "gbif": {"canonicalName": "Camponotus ligniperda"},
                "consensus_species": "Camponotus ligniperda",
                "concordance_status": "CONCORDANT",
                "qc_flag": "OK",
            }
        ]

        app.output_dir_var.set(str(tmp_path))
        app._combine_and_overwrite_results(rerun_resolved, rows)

        # Master results should now have 2 rows, neither failed
        assert len(app.last_results_rows) == 2
        assert app.results_matrix[0][5] == "Camponotus ligniperda"
        assert app._is_row_failed(app.last_results_rows[0]) is False
        assert app.rerun_failed_btn.cget("state") == "disabled"
    finally:
        try:
            root.destroy()
        except Exception:
            pass
