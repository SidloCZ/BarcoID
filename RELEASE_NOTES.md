# BarcoID Release Notes

## Version 0.1.0 (Initial Release)

Multi-Source DNA Barcode Taxonomic Identifier, Cross-Referencer & QC Auditor.

---

### What's New & Key Highlights

- **Four-Way Taxonomic Triangulation:**
  - Automated cross-validation across **Morphological Prior** (field defline/metadata), **BOLD Systems v5** REST API, **NCBI GenBank BLAST** (remote QBLAST with MEGABLAST or local blastn), and **GBIF Taxonomic Backbone**.
  - Concordance status matrix: `CONCORDANT`, `NEW_ASSIGNMENT`, `MISMATCH_ALERT`, `NO_MATCH`.
  - Quality Control auditing: Automated contamination detection (*Homo sapiens* 100% identity, non-target parasites, cross-well swaps).

- **Standalone Zero-Installation Desktop GUI (`BarcoID.exe`):**
  - Modern, responsive 4-step wizard interface designed with high-contrast light theme (`#FFFFFF` background, `#111111` text, `#4C9E45` botanical green accents).
  - High-DPI text and layout scaling for crisp fullscreen display.
  - Interactive **Metadata Spreadsheet Viewer** (`.csv`, `.tsv`, `.xlsx`): preview specimen vouchers and click column headers to assign Morphospecies and Sample ID fields.
  - Interactive **Results Table**: single-cell highlighting on `Concordance_Status` and `QC_Flag`, manual column resizing, and Excel-style double-click column auto-fit.
  - Diagnostics Terminal & Bug Report generator (`Ctrl+Shift+D`).
  - Built-in **Step-by-Step User Guide** (`?` icon button) with visual workflows for all 4 wizard steps.

- **Production-Grade Resiliency:**
  - SHA-256 persistent disk cache (`.id_cache/`) preventing duplicate network queries.
  - Resilient NCBI QBLAST polling handler with stalled RID abandonment and automated backoff.

- **Multi-Format Reporting:**
  - Formatted multi-tab Excel workbook (`.xlsx`) with color-coded concordance matrices.
  - Tabular TSV/CSV exports and Markdown audit logs.

---

### Download Standalone Binaries (No Python Installation Required)

Download the binary for your operating system from the **Assets** section below:
- **Windows (x64):** `BarcoID-Windows-x64.exe`
- **macOS:** `BarcoID-macOS`
- **Linux (x64):** `BarcoID-Linux-x64`

#### Windows SmartScreen Notice ("Windows protected your PC")

Because BarcoID is a newly released open-source scientific tool without a commercial code-signing certificate, Microsoft Defender SmartScreen may display an unrecognized app notice when running it for the first time:
1. Click **"More info"** (*Další informace*).
2. Click **"Run anyway"** (*Přesto spustit*).

*(Alternatively: right-click `BarcoID-Windows-x64.exe` > select **Properties** > check **"Unblock"** at the bottom > click **OK**).*

---

### Python Package Installation (CLI & Developers)

```bash
# Clone and install with CLI & developer tools
git clone https://github.com/SidloCZ/BarcoID.git
cd BarcoID
python -m pip install -e ".[all]"

# Launch CLI or Desktop GUI
barcoid --help
barcoid --gui
```
