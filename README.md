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

---

## Installation

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
