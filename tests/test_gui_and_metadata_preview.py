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
from barcoid.gui import PALETTE, BarcoIDApp, build_config_from_inputs
from barcoid.parsers.metadata import MetadataParser
from barcoid.pipeline import BarcoIDPipeline


def test_palette_primary_green():
    """Verifies that the BIEN-inspired light theme uses #4C9E45 as primary accent."""
    assert PALETTE["primary"] == "#4C9E45"
    assert PALETTE["bg_canvas"] == "#FAF8F5"


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
    finally:
        root.destroy()

