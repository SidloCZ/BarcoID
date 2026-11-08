# BarcoID

**Multi-Source DNA Barcode Taxonomic Identifier, Cross-Referencer & QC Auditor**

BarcoID (`barcoid`) is a high-throughput bioinformatics pipeline and Python library designed to validate, cross-reference, and audit taxonomic assignments of DNA barcodes (COI, rbcL, 16S, ITS). 

Rather than relying on a single reference database, BarcoID triangulates four independent evidence streams to classify concordance, detect contaminations, and flag database conflicts.

---

## Key Features

- **Four-Way Taxonomic Triangulation:**
  1. **Morphological Prior:** Field voucher metadata and preliminary determinations (from FASTA deflines or external spreadsheets).
  2. **BOLD Systems v5:** Official REST API batch submission, polling, percentage identity, and BIN assignment.
  3. **NCBI GenBank BLAST:** Resilient remote QBLAST (or high-throughput local `blastn`) against GenBank `nt` with taxon-specific Entrez queries.
  4. **GBIF Taxonomic Backbone:** Verification of taxonomic status (accepted vs. synonym), hierarchy harmonization, and canonical names (`api.gbif.org`).
- **Automated Concordance Classification:**
  - `CONCORDANT`: Full genus agreement across morphological priors and sequence matches.
  - `NEW_ASSIGNMENT`: Unidentified field specimens (`__` or indeterminate) consistently resolved by BOLD and NCBI.
  - `MISMATCH_ALERT`: Discrepancy between field expectations and database results, or between BOLD and GenBank.
  - `NO_MATCH`: Sequences failing identity thresholds or lacking database matches.
- **QC & Contamination Auditing:**
  - Automated flags for human DNA contamination (*Homo sapiens* 100% identity), cross-well specimen swaps, non-target parasites/endosymbionts (*Wolbachia*, parasitoids, fungi), and low-identity hits.
- **Production-Grade Resiliency:**
  - SHA-256 persistent disk cache (`.id_cache/`) preventing redundant network queries.
  - Resilient NCBI QBLAST polling handler with stalled Request ID (RID) abandonment and automatic retry.
  - Enforcement of `MEGABLAST: 'on'` for rapid nucleotide barcoding.
  - Comprehensive GenBank defline sanitization (stripping `TPA_asm:`, `UNVERIFIED:`, `PREDICTED:`).
- **Multi-Format Reporting:**
  - Stylized multi-tab Excel workbook (`.xlsx`) with conditional color-coded concordance matrices.
  - Pipeline-friendly TSV and CSV tabular exports.
  - Markdown audit summaries suitable for automated documentation.
- **Zero-Installation Desktop App (`BarcoID.exe`):**
  - Standalone single-file executable—download and double-click to launch the light-theme Desktop GUI without installing Python.
  - Built-in **Interactive Metadata Spreadsheet Viewer** (`.csv`, `.tsv`, `.xlsx`): preview your metadata rows inside the app and click any column header to select the **Morphospecies** and **Sample ID** columns.

---

## Download & Run (No Installation Required)

1. Download **`BarcoID-Windows-x64.exe`** (or the macOS / Linux binary) from [GitHub Releases](https://github.com/SidloCZ/BarcoID/releases).
2. Double-click the downloaded executable to launch the Desktop GUI:
   - **Step 1 (Sequences & Parameters):** Click **Browse FASTA** to select your DNA barcode file, adjust target taxon and cache settings.
   - **Step 2 (Metadata Viewer):** Optionally load your specimen spreadsheet (`.csv`, `.tsv`, `.xlsx`) directly in the app table and click the header to pick your **Morphospecies** and **Sample ID** columns.
   - **Step 3 (Run):** Click **Run Identification** to trigger the live 4-stream verification (Morphology, BOLD, NCBI BLAST, GBIF).
   - **Step 4 (Results):** Inspect the interactive table with highlighted concordance and QC flags, double-click headers to auto-fit column widths, and click **Open Excel Report**.

### Windows SmartScreen Notice ("Windows protected your PC")

Because BarcoID is a newly released open-source scientific tool without an expensive commercial code-signing certificate, Microsoft Defender SmartScreen may display an unrecognized app notice when you run it for the first time:

- **Inside the dialog:** Click **"More info"** (*Další informace*) and then click the **"Run anyway"** (*Přesto spustit*) button.
- **Via File Properties:** Right-click `BarcoID-Windows-x64.exe` > select **Properties** (*Vlastnosti*) > check **"Unblock"** (*Odblokovat*) at the bottom > click **OK**.
- **Via PowerShell:** Run `Unblock-File -Path .\BarcoID-Windows-x64.exe`.

---

## Python Package Installation (For Developers & CLI Pipelines)

### From Source

```bash
git clone https://github.com/SidloCZ/BarcoID.git
cd BarcoID
python -m pip install -e .
```

### With Optional Dependencies

```bash
# With Rich terminal progress bars and pandas export
python -m pip install -e ".[all]"
```

---

## Quickstart

### Basic Command-Line Usage

```bash
# Analyze DNA barcodes using the default multi-source engine
barcoid --input barcodes.fasta --output-dir results/
```

### Supplying Morphological Metadata from External CSV

```bash
barcoid --input barcodes.fasta \
        --metadata field_vouchers.csv \
        --sample-col "Voucher_ID" \
        --morpho-col "Field_Morphospecies" \
        --output-dir results/
```

### Filtering by Target Taxon

```bash
# Restrict NCBI BLAST to Formicidae
barcoid --input barcodes.fasta --taxon "Formicidae"
```

---

## Concordance Matrix

| Status | Morphological Prior | BOLD Match | NCBI Match | Interpretation |
| :--- | :--- | :--- | :--- | :--- |
| **`CONCORDANT`** | Genus A | Genus A | Genus A | Confirmed authentic barcode |
| **`NEW_ASSIGNMENT`** | Unassigned (`__`) | Genus A | Genus A | Identified de novo |
| **`MISMATCH_ALERT`** | Genus A | Genus B | Genus B | Possible contamination or mislabeling |
| **`MISMATCH_ALERT`** | Genus A | Genus A | Genus B | Database taxonomy conflict |
| **`NO_MATCH`** | Any | None / Low % | None / Low % | Divergent sequence or novel taxon |

---

## Project Structure

```text
BarcoID/
├── src/
│   └── barcoid/
│       ├── __init__.py          # Version and package entry
│       ├── cli.py               # Command-line interface
│       ├── config.py            # Thresholds and default configuration
│       ├── cache.py             # SHA-256 persistent cache manager
│       ├── parsers/             # FASTA, header regex, and metadata parsers
│       ├── engines/             # BOLD, NCBI QBLAST/local blastn, and GBIF clients
│       ├── arbitration/         # Concordance evaluation and QC discrepancy engine
│       └── exporters/           # Multi-tab Excel, TSV/CSV, and Markdown exporters
├── tests/                       # Unit and integration test suite
├── examples/                    # Sample barcodes and metadata files
├── pyproject.toml               # PEP 517 / 621 package metadata
└── README.md
```

---

## Citation

If you use BarcoID in academic research, please cite:

```bibtex
@software{barcoid2026,
  author = {Šidlík, Jakub},
  title = {BarcoID: Multi-Source DNA Barcode Taxonomic Identifier, Cross-Referencer & QC Auditor},
  year = {2026},
  url = {https://github.com/SidloCZ/BarcoID}
}
```

---

## License

This project is licensed under the [MIT License](LICENSE).

