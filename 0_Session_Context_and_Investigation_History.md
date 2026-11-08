# Session Context, Scientific Findings & AI Continuity Guide

> **Purpose of this Document:**  
> This file provides complete, unambiguous context, diagnostic history, empirical findings, and operational directives for future AI conversations and collaborators working on the **Berlin Nanopore Barcoding Dataset**. Any AI continuing this project should read this document first.

---

## 1. Project Background & Run Metadata

* **Experiment:** Large-scale dual-tagged Nanopore amplicon sequencing of ant (Formicidae) specimens.
* **Sequencing Run:** `UserRun25_26Jan2026` (Flow cell: `PBC38415`, Basecaller: Guppy/Dorado R10.4.1, 400 bps, SUP model).
* **Dataset Scope:** 47 plates of 96-well format (`MJB001` through `MJB047`), encompassing ~5,835 barcode attempts.
* **Target Loci:**
  * **658 bp:** Standard Folmer fragment of mitochondrial Cytochrome c Oxidase Subunit I (COI).
  * **313 bp:** Internal Leray fragment of COI.
* **Primary Pipeline Used:** **ONTbarcoder** (Srivathsan et al., 2021, *BMC Biology*).
* **Collaborators:** Jakub /"Kubeš", Damian, Milan, Kudub.
* **Master Workspace Directory:** `e:/1Coding/Antigravity IDE Projects/BerlinBarcoding`
* **Target Google Drive Folder:** [`1z1jujvtoxVFsyaAdQwYQdUQSwo0owhY8`](https://drive.google.com/drive/folders/1z1jujvtoxVFsyaAdQwYQdUQSwo0owhY8) (*"Unassembled sequences and decontamination"*).

---

## 2. Core Diagnostic Findings & Root Causes

### 2.1 Plate MJB030 (Damian): Tag Collision & Length Mismatch
* **Symptom:** Produced **0 reads** demultiplexed in the 658 bp run.
* **Root Cause 1 (Tag Collision):** In `mergeddemfile_658_27Jan2026_update28Jan2026`, Forward tag `U072` (`CAGCATTGA`) was assigned to both `MJB030` and `MJB032`. Because ONTbarcoder builds an in-memory dictionary keyed on the forward tag, `MJB032` silently overwrote `MJB030`.
* **Root Cause 2 (Fragment Length):** Damian's wet-lab documentation confirms that `MJB030` was amplified with **313 bp Leray primers**, but submitted under the 658 bp pipeline.
* **Empirical Validation:** Inspecting the raw FASTQ (`UserRun25_26Jan2026_total.fastq`) confirmed that reads containing `CAGCATTGA` average **474 bp** (the exact size of a 313 bp amplicon with Nanopore adapters). In the first 1,000 matches, **79 out of 96 reverse tags** were present with high coverage.
* **Resolution Plan (Plan 1):** Re-demultiplex `MJB030` using Forward tag `U072` + 96 reverse tags under the 313 bp pipeline.

---

### 2.2 Plate MJB042 (Jakub): Fragment Length Inversion
* **Symptom:** Produced only **135 total reads** and only 2 barcodes in the 313 bp run; completely absent from 658 bp output.
* **Root Cause:** In `mergeddemfile_313_27Jan2026`, `MJB042` (Forward tag `U082` = `CTGGCTGTT`) was erroneously listed as a 313 bp fragment and omitted from all 658 bp files. In reality, wet-lab material for `MJB042` was amplified using **658 bp Folmer primers**. ONTbarcoder discarded >99% of reads because their length (~662 bp) and primer sequence failed the 313 bp filter.
* **Empirical Validation:** In the first 100,000 raw FASTQ reads alone, tag `CTGGCTGTT` appears 571 times in forward orientation and 347 times in reverse orientation. Out of 500 checked reads, 204 carry the 658 bp Folmer primer (`GGTCAACAAATCATAAAGATATTGG`) and only 3 carry the 313 motif.
* **Resolution Plan (Plan 1):** Re-demultiplex `MJB042` using Forward tag `U082` + 96 reverse tags under the 658 bp pipeline.

---

### 2.3 Kuba's Samples in Batch MJB040 (`JS206`, `JS324`, `JS326`)
* **Context:** Czech ant specimens processed alongside Papua New Guinea (PNG) material.
* **Specimens:**
  1. **`JS206`** (*Liometopum microcephalum*, Brno): Barcode had **100 ambiguous positions (`N`)** and resolved bases were 100% identical to PNG *Nylanderia*.
  2. **`JS324`** (*Messor structor*, Pouzdřanská step): Barcode had **84 ambiguous positions (`N`)**.
  3. **`JS326`** (*Messor structor*, Stolová hora): Barcode had **105 ambiguous positions (`N`)**.

#### The `E, P, Q, F` Alphabet Explained (CRITICAL LESSON):
* In the demultiplexed `.fa` files, exactly 50% of reads contain the characters `E`, `P`, `Q`, `F`.
* **Important Correction:** An earlier conversation hypothesis mistakenly identified these as FASTQ Phred quality score strings. **That was incorrect.**
* **The Proven Reality:** In ONTbarcoder (Srivathsan et al., 2021, *BMC Biology*), reads originating from the reverse complement strand are intentionally recoded into:
  $$\mathbf{E = A},\quad \mathbf{P = T},\quad \mathbf{Q = C},\quad \mathbf{F = G}$$
  This allows MAFFT to align both forward (`ATCG`) and reverse (`EPQF`) reads simultaneously while preserving strand-specific error profiles.
* **Empirical Proof:** When read `901a2d8e` from `JS206_all.fa` was reverse-complemented and mapped ($E \to A, P \to T, Q \to C, F \to G$), it yielded a **100% exact match (650/650 k-mers)** to the raw basecalled read in the FASTQ.
* **DIRECTIVE FOR FUTURE AIS:** **NEVER DELETE `E, P, Q, F` LINES!** Deleting them destroys 50% of sequencing depth. Always **decode** them back to standard DNA.

#### Why Did Kuba's Samples Get 84–105 `N`s?
1. **Low Coverage:** Plate `MJB040` only yielded **30 to 38 total reads** per well (well below optimal 100–200×).
2. **Strand-Concordance Thresholds:** ONTbarcoder requires high agreement between forward (`ATCG`) and reverse (`EPQF`) reads. At low coverage in AT-rich ant genomes (~75% AT) with homopolymer stutter, bases lacking unanimous dual-strand support get assigned an ambiguous **`N`**.
3. **Contaminant Vote-Splitting in `JS206`:** Out of 30 total reads in `JS206`, **4 reads were PNG *Nylanderia*** and **26 reads were genuine *Liometopum***. ONTbarcoder collapsed all reads without haplotype clustering, splitting votes and producing 100 `N`s.
4. **Purity of `JS324` & `JS326`:** Both *Messor* samples are completely free of *Nylanderia*. Their ambiguities resulted solely from low coverage failing ONTbarcoder's consensus threshold.
* **Resolution Plan (Plan 2):** Decode reverse reads ($E \to A, P \to T, Q \to C, F \to G$), partition out the 4 *Nylanderia* reads in `JS206`, and call clean consensus barcodes using all genuine host reads (26–38× depth), achieving **0 `N`s**.

---

### 2.4 Whole-Dataset Contamination Landscape (Plan 3)
A multi-layered contamination profile was revealed by cross-referencing on-disk catalogs:
* **Catalogs on Disk (`Copy of Berlin Data/2Barcode výsledky a práce/Contaminations/`):**
  1. `Berlin_347_Nylanderia_contamination.fasta`: 347 wells across dozens of plates overtaken by PNG *Nylanderia*.
  2. `MJB_contamination_1.fasta`: 292 contaminated barcode assemblies across plates `MJB002` through `MJB047`.
  3. `issues_mismatches.txt`: 13 morphology-vs-sequence mismatch specimens.
  4. `boldigger3_data/..._identification_result.xlsx`: Complete BOLD taxonomic assignments.
  5. `runsummary.xlsx` (6 editions): Per-well demultiplexing and assembly yields.
* **Taxonomic Classes of Contaminants:**
  * ***Nylanderia* (347 wells):** High-titer PNG ant cross-contamination.
  * **Human DNA (*Homo sapiens*, 100% identity, 16+ wells across 9 plates):** Found in `MJB016`, `MJB020`, `MJB028`, `MJB029`, `MJB031`, `MJB032`, `MJB038`, `MJB039`, `MJB045`.
  * **Endosymbionts (*Wolbachia pipientis*):** In `MJB002` and `MJB027`.
  * **Fungi:** *Trichoderma* (`MJB034`), powdery mildew (*Erysiphaceae*, `MJB037`).
  * **Non-Target Arthropods & Parasites:** Parasitoid wasp *Snellenius*, fruit fly *Drosophila*, scuttle fly *Phoridae*, drain fly *Psychodidae*, biting midge *Ceratopogonidae*, broad-headed bug *Riptortus*, beetle *Zopheridae*, nematode *Rhabditidae*.
* **Empirical Proof of Recoverability:** Audited well `Jakub_MJB0001401_MJB015` (flagged as *Nylanderia*, morphologically *Pheidole*):
  * Out of 12 reads (4 forward, 8 reverse), **1 read was *Nylanderia*** and **11 reads were genuine *Pheidole***. Host DNA is physically present and 100% recoverable.

---

### 2.5 Dataset-Wide Diagnostic Audit (All 76 Plates)
An exhaustive bioinformatic audit was performed across all 76 plate spreadsheets in `MJB_ProjectOverview_master.xlsx`, 7,296 demultiplexing configuration rows, 5,835 master consensus barcodes, and 250,000 raw Nanopore sequencing reads:
* **The In-Memory Hash Overwrite Bug:** Keyed as `sampledict[(FTag, RTag)] = sample_name`. Confirmed that across the entire dataset, **exactly two collision events occurred**:
  1. `MJB030` vs `MJB032` in 658 bp (Tag `U072` / `CAGCATTGA`) &rarr; Rescued in Plan 1 (178 barcodes).
  2. `MJB016_redo3` vs `MJB028_redo` in 313 bp (Tag `U068` / `AGTCACCTA`) &rarr; Rescued in Plan 4 (95 barcodes).
  No other plates were erased by hash collisions.
* **Amplicon Length Filtering Inversion:** Plate `MJB042` was the *only* plate in the dataset placed into the wrong amplicon pipeline (658 bp Folmer submitted as 313 bp Leray). Rescued in Plan 1 (84 barcodes).
* **Cross-Pool Forward Tag Sharing:** 22 Forward Tags were used simultaneously across 658 bp and 313 bp pools. They did not overwrite in ONTbarcoder due to separate run files, but require length/primer discrimination during targeted streaming.
* **Master Consensus Duplications:**
  * `MJB021_redo`: Present twice in master records (189 rows total: 95 labeled Jakub, 94 labeled Damian).
  * `MJB033`: 174 rows due to unsuffixed combination of 658 bp and 313 bp runs.

---

### 2.6 Plate MJB016_redo3 (Damian): Disentangled Recovery & Cross-Run Comparison (Plan 4)
* **Symptom:** Produced **0 reads** and **0 barcodes** in the Berlin 313 bp run.
* **Root Cause:** Damian's Solomon Islands plate `MJB016_redo3` (Valavahalo specimens `GUA0444`...) was assigned Forward Tag `U068` (`AGTCACCTA`) and reverse tags `U001`–`U096`. Jakub's PNG plate `MJB028_redo` was assigned the exact same dual indices. In `mergeddemfile_313_27Jan2026`, `MJB028_redo` silently erased `MJB016_redo3`.
* **Empirical Validation:** Dual-tagged reads for Tag `U068` showed that **62 out of 96 wells** contained multiple divergent biological haplotypes.
* **Resolution (Plan 4):** Reads were disentangled using $k$-mer profiling, separating Damian's Solomon Islands material from Jakub's PNG material, followed by MAFFT majority-rule consensus and Table 5 translation checking.
* **Yield:** Rescued **95 consensus barcodes** (69 QC-Compliant with 0 Ns and 0 stop codons, 6 Filtered $\le$1% N, 20 Remaining). Only well 96 (negative control) had 0 consensus.
* **Cross-Run Validation (`redo3` vs `redo2` vs `MJB016` 658 bp):**
  * **Concordance:** 80.0% of shared wells between `redo3` and `redo2` exhibit >=98.0% PID (69 wells 100.0% identical).
  * **Rescue of Missing Specimens:** Recovered 5 biological wells completely absent in `redo2` (including Well 41 `CAMP03_MJ30610`, which matches the Folmer 658 bp barcode at **100.00% exact identity**; and Wells 3, 24, 80 which lacked barcodes across the entire dataset).
  * **Error Correction:** Resolved anomalies in `redo2` (e.g. Well 77 `CAMP02_MJ25051`, where `redo2` diverged at 87.9% from 658 bp, while `redo3` matches authentic 658 bp at 98.7%).
  * **Decontamination Clarification:** Debunked Berlin's false-positive *Nylanderia* contamination flags for `MJB0001453` and `MJB0001490` by verifying true biological morphology (`NYLA03`, `NYLA04`) and 100% sequence fidelity.

---

### 2.7 Multi-Source Taxonomic Identification & 4-Way Comparison Pipeline
* **Context & Motivation:** Need for an automated system replacing outdated BOLDigger to cross-reference newly recovered consensus barcodes across multiple authoritative databases and verify them against field morphological metadata.
* **Implementation (`scripts/multi_source_barcode_identifier.py`):**
  1. **Source 1 (FASTA Header Suffix):** Regex parser extracting collection year, locality (*Valavahalo*, *Yawan*, *Ohu*), field morphospecies code (*PHEI01*, *HYPO03*, *CARE01*), and specimen voucher codes.
  2. **Source 2 (BOLD Systems v5 ID Engine):** REST API client batch-submitting sequences to `https://id.boldsystems.org/submission`, polling results, and extracting percent identity, BOLD BIN URIs, process IDs, and full 7-rank taxonomic lineage.
  3. **Source 3 (NCBI BLASTn):** Remote QBLAST API client batch-querying GenBank `nt` (Formicidae / Hymenoptera), retrieving accessions, titles, identities, and E-values.
  4. **Source 4 (GBIF Taxonomic Backbone):** Automated taxon reconciliation via `https://api.gbif.org/v1/species/match`, verifying accepted genus/species, taxonomic rank, and GBIF keys (with optional ingestion of manual `gbif.org/tools/sequence-id` CSV exports).
  5. **Resilient Disk Cache (`.id_cache/`):** Permanent JSON caching preventing redundant web requests.
* **Results on 115 Filtered Rescued Barcodes (`Filtered_barcodes_1percamb_upto5err.fa`):**
  * **Concordance Breakdown:**
    * **CONCORDANT (34 barcodes, 29.6%):** Full agreement on genus between field morpho-ID, BOLD, and NCBI.
    * **NEW_ASSIGNMENT (61 barcodes, 53.0%):** Wells where field morpho-ID was blank (`__`), successfully assigned to genus/species via consistent BOLD and NCBI hits (*Pheidole*, *Hypoponera*, *Nylanderia*, *Ponera*, *Brachyponera*).
    * **MISMATCH_ALERT (20 barcodes, 17.4%):** Discrepancies between field morpho-ID and sequence match or database conflict.
  * **Critical Contamination & Mislabeling Findings:**
    * **Human DNA Contamination:** Well `MJB0001492_MJB016_redo3` (morphologically labeled `PHEI01`) matched *Homo sapiens* at **100.0% identity** on BOLD.
    * **Cross-Well Swaps / Ant Contaminations:**
      * `MJB0001457_MJB016_redo3` (labeled *Technomyrmex*) matched *Pheidole oceanica* (>96.5% on BOLD and NCBI).
      * `MJB0001468_MJB016_redo3` (labeled *Nylanderia* `NYLA02`) matched *Pheidole* (97.11% on BOLD and NCBI).
      * `MJB0002839_MJB030` (labeled *Rhytidoponera*) matched *Polyrhachis* (>95.6% on BOLD and NCBI).
      * `MJB0002837_MJB030` (labeled *Brachyponera*) matched *Hypoponera* (98.76% on BOLD).
* **Master Deliverable:** `Recovery_and_Decontamination_Outputs/rescued_barcodes_multi_source_identification.xlsx` (Multi-tab workbook containing `Taxonomic_Comparison`, `BOLD_Detailed_Hits`, `NCBI_Detailed_Hits`, and `Discrepancies_and_QC`).

---

## 3. Directory & Plan File Structure

The `Recovery_and_Decontamination_Plans/` folder contains structured execution plans:
* [`0_Session_Context_and_Investigation_History.md`](file:///e:/1Coding/Antigravity%20IDE%20Projects/BerlinBarcoding/Recovery_and_Decontamination_Plans/0_Session_Context_and_Investigation_History.md) *(this file)*: Central contextual bridge, empirical findings, and AI continuity briefing.
* [`1_Plate_Recovery_Plan_MJB030_MJB042.md`](file:///e:/1Coding/Antigravity%20IDE%20Projects/BerlinBarcoding/Recovery_and_Decontamination_Plans/1_Plate_Recovery_Plan_MJB030_MJB042.md): Technical plan for streaming raw reads from `UserRun25_26Jan2026_total.fastq` to demultiplex `MJB030` (658 bp) and `MJB042` (658 bp).
* [`2_Kubeš's_Samples_Recovery_Plan_JS206_JS324_JS326.md`](file:///e:/1Coding/Antigravity%20IDE%20Projects/BerlinBarcoding/Recovery_and_Decontamination_Plans/2_Kubeš's_Samples_Recovery_Plan_JS206_JS324_JS326.md): Technical plan for decoding reverse reads ($E \to A, P \to T, Q \to C, F \to G$), partitioning *Nylanderia*, and calling clean consensus for Jakub's Czech samples.
* [`3_Cross_Plate_Decontamination_Plan.md`](file:///e:/1Coding/Antigravity%20IDE%20Projects/BerlinBarcoding/Recovery_and_Decontamination_Plans/3_Cross_Plate_Decontamination_Plan.md): 4-tier automated decontamination pipeline across all 47 plates using multi-reference screening and haplotype assembly.
* [`4_Plate_Recovery_Plan_MJB016_redo3.md`](file:///e:/1Coding/Antigravity%20IDE%20Projects/BerlinBarcoding/Recovery_and_Decontamination_Plans/4_Plate_Recovery_Plan_MJB016_redo3.md): Technical plan for dataset audit, dual-haplotype disentanglement, and recovery of Damian's Solomon Islands plate `MJB016_redo3`.

---

## 4. Corresponding Google Drive Assets

All plans and outputs are synchronized to the shared team folders:  
* **Root Project Folder:** `https://drive.google.com/drive/folders/1z1jujvtoxVFsyaAdQwYQdUQSwo0owhY8`
* **Outputs Folder:** `https://drive.google.com/drive/folders/1PXr-HQOhygyXCCgEJe8_4WrcbtBWwfYN`
* **Plans Folder:** `https://drive.google.com/drive/folders/1yRoeLUzXm98YcY23r0_Oac76eHV29vAZ`

| Plan / Document | File ID / Link | Target / Scope |
| :--- | :--- | :--- |
| **0. Session Context & Investigation History** | `1DYi8lb8S2unElnSnQX8FEULRMQu14tYh` | Master diagnostic and continuity guide |
| **1. Plate Recovery Plan (MJB030 & MJB042)** | `1fIHYPGMfEPD4Lc_owSDUHrf1MYQidF5N9m5oqbA3v0w` | Rescued 178 authentic 658 bp barcodes |
| **1. Recovery Summary (MJB030 & MJB042)** | `141TzK0fhj-X31CkgIvoq3NBU0bRW7xG8` | Comprehensive output summary and methods paragraph |
| **2. Kuba's Samples (JS206, JS324, JS326)** | `1CcWE9l-W8d9rxhRprBFO0o8rmeRzLOZK20NmLYMURZM` | Recovery of Czech samples |
| **3. Cross-Plate Decontamination** | `1NPNAZI1AiXKJphXakwkUaE48qNcUWn23MBw92dtmkWQ` | Whole-dataset screening and decontamination |
| **4. Plate Recovery Plan (MJB016_redo3)** | *(uploading)* | Dataset audit and haplotype disentanglement |
| **4. Recovery Summary (MJB016_redo3)** | `13dexAU4WJZ-ZA2dfEDRL-wXiqNRN8JSM` | Rescued 95 authentic 313 bp barcodes (69 QC-Compliant) |
| **Multi-Source Identification Workbook** | `1tCIoFt-o6NHJ6vywt5Sty6p_NhOFAEfz` | Master 4-way comparison (.xlsx) across BOLD, NCBI, GBIF, and Suffix |
| **Recovered Consensus Barcodes Folder (Drive Root)** | `1x4RYUlO4VEcJJHBgB2_2lU8JCVuoV5gR` | Main `recovered_consensus_barcodes` folder |
| **- combined_results Folder** | `1xEKE-6BA5QPMDwS4dLWcuJ-NC1YCtICy` | 273 combined barcodes from all 3 rescued plates (101 QC-Compliant) |
| **- MJB016_redo3 Consensus Folder** | `1yQSue8KFdxPgubyOxlhk09uaNnRcYNaq` | 95 rescued barcodes (69 QC-Compliant, 313 bp) |
| **- MJB030 Consensus Folder** | `1QbgnEKyakbfZ-oLz9jiTX3iHH9YAZrdz` | 94 rescued barcodes (30 QC-Compliant, 658 bp) |
| **- MJB042 Consensus Folder** | `1pZE-ZZ0K0_Ea6pNJtAidhClhIEN1TuDq` | 84 rescued barcodes (2 QC-Compliant, 658 bp) |

---

## 5. Operational Constraints & Next Steps for Future AIs

1. **User Execution Constraint:** The user explicitly commanded: *"Dont make the script just answer"*. Do not execute large-scale batch assembly or re-demultiplexing scripts until the user and colleagues have completed their team alignment meeting.
2. **Reverse-Strand Decoding Rule:** When writing scripts to process demultiplexed `.fa` files, always apply:
   ```python
   def decode_ontbarcoder_read(seq: str) -> str:
       # If read is reverse-strand encoded by ONTbarcoder
       if any(c in seq for c in ("E", "P", "Q", "F")):
           tr = str.maketrans("EPQF", "ATCG")
           return seq.translate(tr)
       return seq
   ```
3. **Dropzone Ingestion:** The Google Drive folder is configured as a colleague dropzone. Any newly uploaded spreadsheets, FASTA files, or notes should be integrated into the screening panel and mismatch verification lists.
4. **Preserve User Assets:** Keep the animated reaction GIF (`extracted_gemini_slop.gif`) and playful subtitle (*"slopped by Gemini 3.8 Flash medium"*) intact in the main Google Doc.

---

## 6. Allbarcodes Taxonomic Identification & Engine Resilience Upgrades

- **Target Dataset:** `Recovery_and_Decontamination_Outputs/recovered_consensus_barcodes/combined_results/Allbarcodes.fa` (273 total barcodes across MJB016_redo3, MJB030, and MJB042).
- **Execution & Storage:** Executed locally and placed into a dedicated folder `Recovery_and_Decontamination_Outputs/all_barcodes_identification/` containing `all_barcodes_multi_source_identification.xlsx` and `Allbarcodes_Identification_Summary.md`. **Per explicit user instructions, this run was kept strictly local and was NOT uploaded to Google Drive.**
- **Pipeline Diagnostics & Fixes Applied:**
  1. *NCBI QBLAST Server Stall & Timeout:* Biopython's bare `NCBIWWW.qblast` hung indefinitely on batch 12 (RID `EU0FZ6BY016` in `Status=WAITING` for >35 min). Replaced with custom `qblast_xml` featuring a 150-second timeout, `MEGABLAST: 'on'` enforcement, and 5-sequence batching.
  2. *GenBank TPA Defline Sanitization:* GenBank Third-Party Annotation accessions (`|tpg|`) starting with `TPA_asm:` were originally capturing `TPA_asm:` as the genus. Added multi-database prefix stripping regex (`|tpg|`, `|emb|`, `|dbj|`, `|ref|`), successfully restoring genuine genera (*Aphomomyrmex*, *Tapinolepis*, etc.).
  3. *Delimiter-Aware Year Parsing:* Word boundary regex `\b(19\d{2}|20\d{2})\b` failed when years were delimited by underscores (`_2017_`). Updated regex to `(?:^|_)(19\d{2}|20\d{2})(?:_|$)`, ensuring years populate cleanly and locality fields are stripped of year numbers.
  4. *GBIF Demarcation:* Clarified that GBIF functions as a Taxonomic Backbone validation and synonym-resolution engine rather than a de novo BLAST search.
- **Results:** 41 Concordant (15.0%), 187 New Assignment (68.5%), 32 Mismatch Alert (11.7%), 13 No Match (4.8%). Top genera: *Pheidole* (60), *Nylanderia* (36), *Hypoponera* (13). Human contamination (*Homo sapiens*, 100%) flagged in sample `MJB0001492_MJB016_redo3`.


