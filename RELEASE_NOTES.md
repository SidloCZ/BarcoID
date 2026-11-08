# BarcoID Release Notes

## Version 0.2.0

**Multi-Source DNA Barcode Taxonomic Identifier, Cross-Referencer & QC Auditor**

---

### What's New & Key Highlights in Version 0.2.0

- **Authentic 4-Step Interactive User Guide:**
  - Upgraded the in-app Step-by-Step User Guide dialog (`?` button) with official high-resolution interface captures for all 4 wizard steps.
  - Implemented automatic high-DPI image subsampling so guide screenshots render crisply on any display scaling without horizontal overflow.

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
