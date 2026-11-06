# Project Plan: BarcoID (Multi-Source DNA Barcode Taxonomic Identifier & Validator)

## 1. Executive Summary

**Project Name:** **BarcoID**  
**Package / Import Name:** `barcoid`  
**CLI Command:** `barcoid` (alias: `barco-id`)  
**Tagline:** Multi-Source DNA Barcode Taxonomic Identifier, Cross-Referencer & QC Auditor  
**Repository Target:** GitHub (Public Open Source)  
**Target Ecosystem:** PyPI (`pip install barcoid`), Bioconda (`conda install -c bioconda barcoid`), Docker / Singularity  
**Origin:** Refactored, generalized, and elevated from the bioinformatic pipeline `multi_source_barcode_identifier.py` (BerlinBarcoding project).

### The Scientific Need
DNA barcoding (COI, rbcL, 16S, ITS) frequently relies on single-source taxonomic identification engines (e.g., querying only BOLD Systems or running remote/local BLAST against NCBI GenBank). This presents severe pitfalls:
- BOLD and GenBank frequently diverge due to differing taxonomic curations, misidentified public submissions, or synonymies.
- Morphological field identifications (voucher morphospecies) are often lost or siloed in separate spreadsheets during sequencing.
- Cross-contamination and barcode-sharing across wells or specimens often go undetected unless systematically audited against prior morphological expectations.

### The Solution
A unified, standalone CLI and Python library that automatically cross-references recovered DNA barcodes against **four independent evidence streams**:
1. **Morphological Prior:** Field voucher metadata and preliminary morphological assignments (from FASTA deflines or external metadata spreadsheets).
2. **BOLD Systems v5:** Official REST API batch submission, polling, percent identity, and BIN assignment.
3. **NCBI GenBank BLAST:** Resilient QBLAST (or high-throughput local `blastn`) against nucleotide databases with taxon-specific filters.
4. **GBIF Taxonomic Backbone:** Verification of taxonomic status (accepted vs. synonym), hierarchy harmonization, and canonical names.

The engine computes an automated **Concordance Matrix** (`CONCORDANT`, `NEW_ASSIGNMENT`, `MISMATCH_ALERT`, `NO_MATCH`) and generates **QC Discrepancy Flags** (`OK`, `CONTAMINATION_SUSPECT`, `LOW_IDENTITY`, `DATABASE_CONFLICT`).

---

## 2. Naming & Branding Rationale

**Selected Name:** **`BarcoID`** (`barcoid`)

| Attribute | Details |
| :--- | :--- |
| **Package Name** | `barcoid` |
| **CLI Binaries** | `barcoid` (primary) and `barco-id` (alias) |
| **Python Import** | `import barcoid` |
| **Why Selected** | Compact (7 letters), memorable, natural contraction of **Barco**de **ID**entifier. Solves the retail/QR-code search collision on PyPI/GitHub, rolls off the tongue in conversations and papers, and makes for a super clean CLI command (`$ barcoid --input barcodes.fasta`). |
| **Moniker References** | Incorporates the "BBG" triangulation principle (BOLD + BLAST + GBIF) alongside morphological priors. |

---

## 3. Core Capabilities & Architectural Design

### 3.1 Modular Architecture

The tool transitions from a single script to a decoupled, production-grade Python package:

```text
BarcoID/
├── .github/
│   └── workflows/
│       ├── test.yml             # Matrix testing: Ubuntu, macOS, Windows (Python 3.9 - 3.12)
│       ├── lint.yml             # Ruff / Flake8 / Black code formatting
│       └── publish.yml          # Automated PyPI & GitHub Releases on git tag
├── src/
│   └── barcoid/
│       ├── __init__.py          # Package metadata & version (__version__)
│       ├── cli.py               # Command-line interface (argparse / click)
│       ├── config.py            # Default thresholds, API endpoints, rate limits
│       ├── cache.py             # SHA-256 persistent disk cache (JSON / SQLite)
│       ├── parsers/
│       │   ├── __init__.py
│       │   ├── fasta.py         # Standard FASTA reader
│       │   ├── headers.py       # Configurable regex defline parser
│       │   ├── ontbarcoder.py   # Specialized ONTbarcoder header statistics parser
│       │   └── metadata.py      # External CSV/TSV metadata joiner
│       ├── engines/
│       │   ├── __init__.py
│       │   ├── bold.py          # BOLD v5 REST API batch submission & polling
│       │   ├── blast_remote.py  # Resilient NCBI QBLAST with megablast, timeout & stalled RID recovery
│       │   ├── blast_local.py   # Local blastn subprocess runner for offline / high-throughput
│       │   └── gbif.py          # GBIF Species Match Backbone API client & Sequence-ID CSV parser
│       ├── arbitration/
│       │   ├── __init__.py
│       │   ├── concordance.py   # Consensus arbitration & concordance classification
│       │   └── qc.py            # QC flagging (contamination, low identity, conflicts)
│       └── exporters/
│           ├── __init__.py
│           ├── excel.py         # Multi-tab styled Excel workbook (.xlsx)
│           ├── tabular.py       # TSV / CSV table exports for bioinformatics pipelines
│           └── report.py        # Terminal summary and Markdown audit report
├── tests/
│   ├── test_cache.py
│   ├── test_parsers.py
│   ├── test_concordance.py
│   ├── test_qc.py
│   └── mocks/                   # Offline mock responses for BOLD, NCBI, and GBIF
├── docs/
│   ├── index.md
│   ├── quickstart.md
│   ├── cli_reference.md
│   ├── methodology.md
│   └── tutorials/
│       ├── ants_example.md
│       └── generic_invertebrates.md
├── examples/
│   ├── sample_barcodes.fasta
│   └── sample_metadata.csv
├── pyproject.toml               # Modern standard packaging (PEP 517 / 621)
├── README.md                    # Comprehensive documentation with badges
├── LICENSE                      # Open-source license (MIT or Apache 2.0)
└── CITATION.cff                 # Academic citation file
```

---

## 4. Key Functional Improvements Over the Prototype

### 4.1 Taxonomic Generalization
- **Decouple hardcoded Formicidae:** The prototype contained fixed ant genus tables and `txid36668`.
- **Configurable Scope:** Users specify `--taxon "Insecta"`, `--taxon "Formicidae"`, `--taxon "Fungi"`, or a specific NCBI Entrez query via `--entrez-query`.
- **Morphospecies Prefix Maps:** Users can supply custom prefix-to-genus maps via `--prefix-map prefixes.json` or `--prefix-map prefixes.csv` for field codes (e.g. `PHEI01` -> `Pheidole`).

### 4.2 Flexible Metadata Ingestion
1. **Header Parsing Mode:** Retains robust extraction of sample ID, year, morphospecies, locality, and voucher from FASTA deflines.
2. **Tabular Metadata Mode:** Ingests clean FASTA files (`>SampleID`) and links them with an external metadata sheet:
   ```bash
   barcode-id --input sequences.fasta --metadata field_data.csv --sample-col "Voucher_ID" --morpho-col "Field_Morphospecies"
   ```

### 4.3 High-Throughput & Offline Execution
- **Local BLASTn Support:** For datasets exceeding 500 barcodes, querying remote NCBI QBLAST can take hours and face network bottlenecks. The tool will support `--local-blast-db /path/to/nt_or_midori` using local `blastn` binaries.
- **NCBI Compliance:** Full integration of `--ncbi-email` and `--ncbi-api-key` (raising NCBI rate limits from 3 to 10 queries/second).

### 4.4 Automated Multi-Format Outputs
- **Interactive Multi-Tab Excel (.xlsx):**
  - Sheet 1: Master Taxonomic Comparison
  - Sheet 2: BOLD Detailed Hits (all hits, BINs, process IDs, pdist)
  - Sheet 3: NCBI Detailed Hits (accessions, bitscores, e-values, alignments)
  - Sheet 4: Discrepancies & Contamination QC (auto-filtered view of flags)
- **Pipeline-Friendly Tabular Files (.tsv / .csv):** Direct integration into Snakemake, Nextflow, or R (`tidyverse`).
- **Markdown Summary Report (.md):** Suitable for GitHub pull request comments or automated audit logging.

### 4.5 Production Resiliency & Lessons Learned from BerlinBarcoding Benchmark
Empirical testing on 273 Oxford Nanopore full-length (658 bp) and mini-barcodes (313 bp) revealed several critical real-world edge cases that the standalone package must proactively guard against:

1. **NCBI Remote QBLAST Stall & Indefinite Polling Vulnerability:**
   - *Problem:* Biopython's default `NCBIWWW.qblast` lacks a polling timeout; it issues a `BiopythonWarning` after 10 minutes but continues polling forever in an infinite `while True:` loop. When NCBI's public cluster stalls on a single Request ID (e.g., job queued behind heavy server load or assigned to an unresponsive worker node), execution freezes indefinitely.
   - *Architecture Fix:* Replace bare Biopython polling with a custom, resilient polling handler (`blast_remote.py`) featuring:
     - Strict per-request polling timeout (e.g. 120–150 seconds).
     - Automated abandonment of stalled RIDs with graceful fallback (`NO_MATCH` / `TIMEOUT_ALERT`) and single-retry logic.
     - Mandatory enforcement of `MEGABLAST: 'on'` for nucleotide DNA barcoding, accelerating batch processing from minutes to 10–15 seconds per batch.
     - Adaptive batch sizing: Default to 5 sequences (rather than 10+) to avoid NCBI worker queue load spikes on long (658 bp) consensus sequences containing IUPAC ambiguities.

2. **GenBank Defline Sanitization & Multi-Database Prefix Handling:**
   - *Problem:* GenBank titles often originate from Third-Party Annotations (`|tpg|` accessions starting with `TPA_asm: Genus species`), EMBL (`|emb|`), DDBJ (`|dbj|`), or RefSeq (`|ref|`). Naive regex looking only for `|gb|` fails, and simple whitespace token splitting incorrectly captures `TPA_asm:`, `UNVERIFIED:`, or `PREDICTED:` as the organism's genus name.
   - *Architecture Fix:* Implement comprehensive multi-database regex sanitization (`r'>?gi\|\d+\|(?:gb|emb|dbj|tpg|ref)\|([\w\.]+)\|\s*(?:TPA(?:_asm)?:\s*)?([A-Za-z]+)\s+([A-Za-z0-9\.\_\-]+)'`) that cleanly strips `TPA_asm:`, `UNVERIFIED:`, and `PREDICTED:` prefixes before extracting valid binominal genera and species names.

3. **Delimiter-Aware Metadata Token Extraction:**
   - *Problem:* Python regex word boundary `\b` treats underscores (`_`) as word characters (`\w`). Consequently, boundary checks like `\b(19\d{2}|20\d{2})\b` fail when tokens are joined by underscores (e.g., `_2017_` or `_2004_`), causing collection years to be missed and improperly retained inside locality strings.
   - *Architecture Fix:* In `parsers/headers.py`, use explicit delimiter-aware matching (`(?:^|_)(19\d{2}|20\d{2})(?:_|$)`) and token-based suffix splitting.

4. **Explicit GBIF Role Demarcation & Live Progress Feedback:**
   - *Problem:* Users often mistake GBIF for a third de novo sequence alignment tool and wonder why it doesn't run BLAST, or believe it was skipped due to silent execution.
   - *Architecture Fix:*
     - Demarcate GBIF's role in CLI docs and output reports as a **Taxonomic Backbone Validation & Synonym Resolution Engine** (`api.gbif.org/v1/species/match`), validating sequence hits and resolving deprecated synonyms to accepted valid names.
     - Implement live visual progress bars (via `rich`) showing active GBIF lookups, match rates, and synonym-to-accepted resolution stats.
     - Provide dedicated support for ingestion of GBIF Sequence-ID BLAST CSV exports (`--gbif-csv`).

---

## 5. Development Roadmap & Milestones

```text
Phase 1: Project Setup & Package Scaffolding
- Initialize Git repository and directory layout.
- Configure pyproject.toml with metadata, dependencies, and CLI entrypoint.
- Setup pre-commit hooks and GitHub Actions CI workflow.

Phase 2: Modular Code Extraction & Decoupling
- Extract CacheManager into barcoid.cache.
- Modularize BOLD, NCBI, and GBIF API clients with retry logic and rate limiters.
- Implement resilient NCBI QBLAST polling handler (150s timeout, megablast enforcement, stalled RID abort & recovery).
- Parameterize taxonomic targets (replace hardcoded ant genera with generic configuration).

Phase 3: Parsing & Metadata Ingestion
- Implement standalone FASTA parser.
- Implement delimiter-aware FASTA defline parser with GenBank title / TPA prefix sanitization.
- Implement ONTbarcoder statistics extractor.
- Implement external CSV/TSV metadata matching engine.

Phase 4: Concordance Engine & QC Auditing
- Port and unit test the 4-way concordance scoring logic.
- Implement contamination detection rules and identity thresholds.
- Implement tabular and styled Excel exporters.

Phase 5: Local BLAST Support & Testing
- Add local blastn runner via subprocess.
- Build comprehensive test suite with offline mock API responses.
- Write documentation, quickstart guide, and example datasets.

Phase 6: Open-Source Release
- Publish to GitHub.
- Publish package to PyPI (pip install barcoid).
- Submit Bioconda recipe (conda-forge / bioconda).
```

---

## 6. Technical Stack & Dependencies

- **Language:** Python 3.9+
- **Core Dependencies:**
  - `biopython >= 1.81` (Sequence parsing, BLAST XML handling)
  - `requests >= 2.28` (REST API clients for BOLD and GBIF)
  - `openpyxl >= 3.1` (Excel generation, styling, and conditional formatting)
  - `urllib3 >= 2.0` (HTTP connection pooling and retry mechanisms)
- **Optional / Performance Dependencies:**
  - `rich` (Terminal progress bars, colored logging, and summary tables)
  - `pandas` (Fast tabular manipulation and parquet export)
- **Testing & Quality:**
  - `pytest` + `pytest-mock`
  - `ruff` (Fast linting and code formatting)

---

## 7. Licensing & Attribution

- **Recommended License:** MIT License or Apache License 2.0 (permissive, industry and academia standard).
- **Academic Citation:** Include `CITATION.cff` and `zenodo.json` to enable automated DOI generation via Zenodo upon every GitHub release.
- **Credit:** Acknowledge initial development within Oxford Nanopore DNA barcoding recovery workflows (BerlinBarcoding project).

