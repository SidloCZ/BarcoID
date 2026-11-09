# BarcoID Identification & QC Audit Report

**Total Barcodes Analyzed:** 10

## 1. Concordance Breakdown

| Concordance Status | Count | Percentage |
| :--- | :--- | :--- |
| **`CONCORDANT`** | 5 | 50.0% |
| **`NEW_ASSIGNMENT`** | 1 | 10.0% |
| **`MISMATCH_ALERT`** | 1 | 10.0% |
| **`NO_MATCH`** | 3 | 30.0% |

## 2. Quality Control & Discrepancy Flags

| QC Flag | Count | Interpretation |
| :--- | :--- | :--- |
| **`OK`** | 5 | Consistent authentic barcode |
| **`NO_DATA`** | 3 | No database matches found |
| **`DATABASE_CONFLICT`** | 1 | Taxonomic dispute between BOLD and GenBank |
| **`LOW_IDENTITY`** | 1 | Identity below 90% threshold |

## 3. Flagged Specimens (Discrepancy Highlights)

| Sample ID | Field ID | BOLD Match | NCBI Match | QC Flag |
| :--- | :--- | :--- | :--- | :--- |
| MJB0001427_MJB016_redo3 | Hypoponera |  (0.0%) |  (0.0%) | **`NO_DATA`** |
| MJB0001428_MJB016_redo3 |  |  (0.0%) |  (0.0%) | **`NO_DATA`** |
| MJB0001429_MJB016_redo3 |  |  (0.0%) |  (0.0%) | **`NO_DATA`** |
| MJB0001433_MJB016_redo3 |  | Rhytidoponera cf. araneoides (95.21%) | Tetramorium steinheili (86.9%) | **`DATABASE_CONFLICT`** |
| MJB0001435_MJB016_redo3 |  |  (0.0%) | Tapinolepis sp. (87.22%) | **`LOW_IDENTITY`** |
