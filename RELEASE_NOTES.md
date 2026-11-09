# BarcoID Release Notes

## Version 0.3.1

**Bug SVG Navigation, One-Click GitHub Issue Reporting & Metadata Parser Resilience**

---

### What's New & Key Highlights in Version 0.3.1

- **Bug SVG Icon & Quick Diagnostics Access:**
  - Added a clean, minimalist, anti-aliased SVG bug icon button in the top navigation header positioned directly to the left of the `?` help button.
  - Clicking the bug icon immediately opens (or brings to the front) the Diagnostic Terminal & Bug Report window (`Ctrl+Shift+D`).
  - Implemented anti-aliased pure-Python RGBA vector rasterization with true transparency for crisp rendering across all display DPI scales.

- **One-Click "Report issue" Button for GitHub:**
  - Added a dedicated "Report issue" button in the diagnostics window header.
  - Automatically compiles complete diagnostic information including BarcoID version, OS/platform details, Python runtime, active dataset parameters, full exception traceback, and recent execution logs.
  - Copies the complete, unabridged diagnostic report text to the system clipboard for effortless reference.
  - Launches the default browser to `https://github.com/SidloCZ/BarcoID/issues/new` with pre-filled title and structured GitHub Markdown issue body.

- **Metadata Parser Resilience & Keyword Argument Compatibility:**
  - Resolved `TypeError: MetadataParser.__init__() got an unexpected keyword argument 'sample_id_col'` reported during runs with custom external metadata files.
  - Added full backward-compatible keyword aliases (`sample_id_col`, `morphospecies_col`) in `MetadataParser.__init__`.
  - Added public `MetadataParser.load(metadata_path)` method for two-phase instantiation.
  - Upgraded sample ID matching with progressive prefix token matching and case-insensitive resolution, ensuring external metadata rows reliably link to specimen FASTA deflines regardless of suffix formatting.

---

## Version 0.3.0

**Progressive Results Chunking, Resilient Multi-Thread Caching, Dynamic ETA & Window Close Protection**

---

### What's New & Key Highlights in Version 0.3.0

- **Progressive Execution & Incremental Preliminary Exports:**
  - Sequences can now be processed in configurable incremental chunks (default: 50 sequences, options: 25, 50, 100, 200).
  - Preliminary concordance and QC evaluations are automatically written to `*_preliminary.xlsx` and streamed to the UI after every completed chunk.
  - Users can inspect partially completed identifications without waiting for thousands of sequences to finish.
  - Toggleable via GUI checkbox in Step 3 and CLI (`--enable-preliminary` / `--no-preliminary`, `--preliminary-interval <N>`).

- **Interactive "Check Preliminary Results" Navigation:**
  - Added a dynamic **"Check Preliminary Results (N)"** button in Step 3 that lights up as soon as the first chunk completes.
  - Clicking seamlessly switches to **Step 4: Results** with live-updating tables and concordance metric cards.
  - Step 4 now features a dedicated **"Back to Active Run"** button allowing seamless toggling between live inspection and the active execution monitor.

- **Dynamic Real-Time Time Estimation (ETA):**
  - Step 3 now computes and displays comprehensive live execution statistics:
    `Elapsed: MM:SS | ETA: ~MM:SS | Speed: X.X seq/s | Completed: X / Y (Z%)`.
  - Automatically factors in actual network response times and cache hit ratios.

- **Run in Progress Exit Guard:**
  - Added native `WM_DELETE_WINDOW` protection that intercepts window close requests while an identification run is active.
  - Displays a clean warning modal confirming whether to abort the active run, ensuring users do not accidentally close the app and lose in-flight network batches.

- **Multi-Thread Cache Thread-Safety & Windows/OneDrive Resilience:**
  - Replaced monolithic file saves with thread-safe `threading.RLock()` and isolated engine flushes (`save_bold()`, `save_ncbi()`, `save_gbif()`).
  - Implemented per-thread unique temporary files (`{stem}_{pid}_{thread}_{uuid}.tmp`) eliminating `[WinError 32]` lock collisions in cloud-synced folders (OneDrive, Dropbox) and antivirus scanners.
  - Added exponential retry loops for atomic file replacements.
  - Added `CacheManager.prune_empty()` and CLI `--prune-cache` to clean false-negative cache entries without purging valid hits.

- **BOLD Systems v5 Quality Pre-Screening & HTTP 400 Isolation:**
  - Sequences with `< 75%` standard `[ACGT-]` nucleotides or length `< 20 bp` are automatically pre-screened, logged with a clear QC note, and excluded from BOLD query batches to prevent HTTP 400 rejections.
  - Added adaptive batch bisecting and label isolation so a single low-quality sequence never drops other valid sequences in the batch.

- **NCBI QBLAST HTML Congestion Detection & Cache Protection:**
  - Added detection for HTML error/congestion pages from NCBI, raising proper backoff exceptions instead of treating missing RIDs as negative matches.
  - Failed or timed-out NCBI queries are never poisoned into the persistent disk cache as false negatives.
  - Added `--skip-ncbi` (alias `--no-ncbi`) option in CLI and GUI to bypass remote QBLAST on large datasets (>150 sequences) when a local BLAST database is unavailable.

---

## Version 0.2.0

**Multi-Source DNA Barcode Taxonomic Identifier, Cross-Referencer & QC Auditor**

---

### What's New & Key Highlights in Version 0.2.0

- **Authentic 4-Step Interactive User Guide:**
  - Upgraded the in-app Step-by-Step User Guide dialog (`?` button) with official high-resolution interface captures for all 4 wizard steps.
  - Enlarged the guide window to 1040x840 so screenshots render at 100% full original sharp resolution.
  - Added recursive mouse wheel scrolling across all cards, labels, images, and backgrounds throughout the guide dialog.

- **Author Tag & Quick Access:**
  - Added a clean, minimalist "Made by SidloCZ" attribution tag positioned immediately to the left of the Help (`?`) icon in the desktop header.
  - Interactive hover state and direct hyperlink to GitHub profile (`https://github.com/SidloCZ`).

- **Overhauled Formicidae Demo Dataset:**
  - Replaced prototype test data with 20 diverse, realistic ant (*Formicidae*) COI barcode sequences and rich metadata in `examples/sample_barcodes.fasta` and `examples/sample_metadata.csv`.
  - Representative test scenarios included:
    - Full concordant matches across major ant subfamilies (*Camponotus vagus*, *Lasius niger*, *Formica rufa*, *Solenopsis invicta*, *Tetramorium caespitum*, *Polyrhachis dives*, *Colobopsis truncata*, *Pseudomyrmex gracilis*, *Nylanderia fulva*).
    - Morphospecies codes demonstrating automatic genus prior inference (`PHEI01`, `ODON01`, `CREM01`, `HYPO01`, `STRO01`, `BRACH01`).
    - Undetermined field specimens demonstrating automated `NEW_ASSIGNMENT` resolution.
    - Intentional field misidentifications showcasing automated `MISMATCH_ALERT` protection.
    - PCR primer trims and natural IUPAC nucleotide ambiguities (`N`, `R`).

- **Clarified GBIF Taxonomic Backbone Role in Documentation:**
  - Expanded `README.md`, `PLAN.md`, and engine docstrings detailing the distinct bioinformatic roles of BOLD Systems v5 and NCBI GenBank (sequence alignment) versus the GBIF Taxonomic Backbone (`api.gbif.org/v1/species/match`) as the nomenclatural authority for synonym resolution and accepted status validation.

- **Standalone Binary Packaging:**
  - Bundled updated assets, guide captures, and multi-resolution PNG/ICO icons into the single-file `BarcoID.exe` distribution.

---

### Download Standalone Binaries (No Python Installation Required)

Download the binary for your operating system from the **Assets** section below:
- **Windows (x64):** `BarcoID-Windows-x64.exe` (or `BarcoID.exe`)
- **macOS:** `BarcoID-macOS`
- **Linux (x64):** `BarcoID-Linux-x64`

#### Windows SmartScreen Notice ("Windows protected your PC")

Because BarcoID is a newly released open-source scientific tool without an expensive commercial code-signing certificate, Microsoft Defender SmartScreen may display an unrecognized app notice when running it for the first time:

1. Click **"More info"** (*Další informace*).
2. Click **"Run anyway"** (*Přesto spustit*).

*(Alternatively: right-click `BarcoID.exe` > select **Properties** > check **"Unblock"** at the bottom > click **OK**).*

---

### Python Package Installation (CLI & Developers)

```bash
# Clone repository
git clone https://github.com/SidloCZ/BarcoID.git
cd BarcoID

# Install in editable mode with optional terminal and tabular extensions
python -m pip install -e ".[all]"

# Launch CLI or Desktop GUI
barcoid --help
barcoid --gui
```

---

## Version 0.1.0 (Initial Release)

- Initial release of the 4-way taxonomic triangulation pipeline (Morphology, BOLD, NCBI BLAST, GBIF).
- Automated concordance matrix and QC discrepancy auditing.
- Standalone zero-installation desktop GUI with interactive metadata spreadsheet viewer.
- Stylized multi-tab Excel reporting, TSV/CSV exports, and Markdown summaries.
