"""
Master pipeline orchestrator for BarcoID.
"""

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from barcoid.arbitration.concordance import ConcordanceEngine
from barcoid.arbitration.qc import QcAuditor
from barcoid.cache import CacheManager
from barcoid.config import BarcoIDConfig
from barcoid.engines.blast_local import LocalBlastEngine
from barcoid.engines.blast_remote import RemoteBlastEngine
from barcoid.engines.bold import BoldEngine
from barcoid.engines.gbif import GbifEngine
from barcoid.engines.rate_limiter import PacingAdvisor
from barcoid.exporters.excel import ExcelExporter
from barcoid.exporters.report import ReportExporter
from barcoid.exporters.tabular import TabularExporter
from barcoid.parsers.fasta import FastaParser
from barcoid.parsers.headers import HeaderParser
from barcoid.parsers.metadata import MetadataParser
from barcoid.parsers.ontbarcoder import OntbarcoderParser

logger = logging.getLogger("barcoid.pipeline")


class BarcoIDPipeline:
    """Executes the complete multi-source DNA barcode identification workflow."""

    def __init__(self, config: BarcoIDConfig):
        self.config = config
        self.cache_manager = CacheManager(config.cache_dir)
        self.header_parser = HeaderParser(custom_prefix_map=config.custom_prefix_map)
        self.ont_parser = OntbarcoderParser()
        self.concordance_engine = ConcordanceEngine(config)
        self.qc_auditor = QcAuditor(config)

    def run(
        self,
        fasta_path: Path,
        metadata_path: Optional[Path] = None,
        sample_col: str = "sample_id",
        morpho_col: str = "field_morphospecies",
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Executes the multi-source pipeline end-to-end."""

        def _notify(stage: str, pct: float):
            if progress_callback:
                try:
                    progress_callback(stage, pct)
                except Exception:
                    pass

        _notify("Step 1/5: Ingesting FASTA sequences and morphological metadata...", 10.0)

        # 1. Ingest sequences
        sequences = FastaParser.read_sequences(fasta_path, max_sequences=self.config.max_sequences)
        if not sequences:
            logger.warning("No sequences found in input file.")
            _notify("No sequences found in input file.", 100.0)
            return []

        # 2. Ingest external metadata if supplied
        meta_parser = None
        if metadata_path and Path(metadata_path).exists():
            meta_parser = MetadataParser(
                metadata_path,
                sample_col=sample_col,
                morpho_col=morpho_col,
                custom_prefix_map=self.config.custom_prefix_map,
            )

        # 3. Workload safety audit
        uncached_bold = sum(1 for _, seq in sequences if not self.cache_manager.get_bold(seq))
        uncached_ncbi = sum(1 for _, seq in sequences if not self.cache_manager.get_ncbi(seq))
        warning = PacingAdvisor.audit_workload(
            uncached_ncbi,
            has_local_db=bool(self.config.local_blast_db and Path(self.config.local_blast_db).exists()),
        )
        if warning:
            logger.warning("=" * 70)
            logger.warning(warning)
            logger.warning("=" * 70)

        if self.config.dry_run:
            logger.info(
                f"[Dry Run Summary] Total sequences: {len(sequences)}, "
                f"Uncached BOLD: {uncached_bold}, Uncached NCBI: {uncached_ncbi}"
            )
            _notify(
                f"Dry run complete: {len(sequences)} sequence(s) inspected "
                f"({uncached_bold} uncached BOLD, {uncached_ncbi} uncached NCBI).",
                100.0,
            )
            return []

        # 4. Engine executions
        _notify("Step 2/5: Querying BOLD Systems v5 Identification Engine...", 25.0)
        bold_engine = BoldEngine(self.config, self.cache_manager)
        bold_results = bold_engine.identify_sequences(sequences)

        _notify("Step 3/5: Querying NCBI GenBank BLAST...", 55.0)
        if self.config.local_blast_db and Path(self.config.local_blast_db).exists():
            blast_engine = LocalBlastEngine(self.config, self.cache_manager)
            ncbi_results = blast_engine.identify_sequences(sequences)
        else:
            remote_engine = RemoteBlastEngine(self.config, self.cache_manager)
            ncbi_results = remote_engine.identify_sequences(sequences)

        # 5. Extract candidate names for GBIF standardization
        _notify("Step 4/5: Harmonizing taxonomy with GBIF Backbone...", 80.0)
        gbif_engine = GbifEngine(self.config, self.cache_manager)
        candidate_names = []
        for hdr, _ in sequences:
            b_tax = bold_results.get(hdr, {}).get("top_species") or bold_results.get(hdr, {}).get("top_genus")
            n_tax = ncbi_results.get(hdr, {}).get("top_species") or ncbi_results.get(hdr, {}).get("top_genus")
            if b_tax:
                candidate_names.append(b_tax)
            if n_tax:
                candidate_names.append(n_tax)

        gbif_results = gbif_engine.match_batch(candidate_names)

        # 6. Synthesize metadata, evaluate concordance, and run QC
        _notify("Step 5/5: Computing Concordance Matrix & exporting reports...", 90.0)
        rows: List[Dict[str, Any]] = []
        for hdr, _ in sequences:
            parsed_meta = self.header_parser.parse_header(hdr)
            ont_stats = self.ont_parser.parse_stats(hdr)
            parsed_meta.update(ont_stats)

            # Override/complement with external metadata if available
            if meta_parser:
                ext_meta = (
                    meta_parser.get_metadata(parsed_meta["sample_id"])
                    or meta_parser.get_metadata(parsed_meta["clean_id"])
                    or meta_parser.get_metadata(parsed_meta.get("voucher_code", ""))
                )
                if ext_meta:
                    if ext_meta.get("field_morpho_code"):
                        parsed_meta["field_morpho_code"] = ext_meta["field_morpho_code"]
                    if ext_meta.get("field_inferred_genus"):
                        parsed_meta["field_inferred_genus"] = ext_meta["field_inferred_genus"]

            b_res = bold_results.get(hdr, {})
            n_res = ncbi_results.get(hdr, {})

            # Match top candidate name in GBIF results
            target_name = b_res.get("top_species") or n_res.get("top_species") or b_res.get("top_genus") or ""
            g_res = gbif_results.get(target_name, {})

            c_genus, c_species, status, conf = self.concordance_engine.evaluate(
                parsed_meta["field_inferred_genus"], b_res, n_res, g_res
            )
            qc_flag = self.qc_auditor.audit(parsed_meta["field_inferred_genus"], b_res, n_res, status)

            rows.append({
                "meta": parsed_meta,
                "bold": b_res,
                "ncbi": n_res,
                "gbif": g_res,
                "consensus_genus": c_genus,
                "consensus_species": c_species,
                "concordance_status": status,
                "confidence_score": conf,
                "qc_flag": qc_flag,
            })

        # 7. Export outputs
        out_dir = Path(self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        stem = Path(fasta_path).stem
        xlsx_path = out_dir / f"{stem}_multi_source_identification.xlsx"
        tsv_path = out_dir / f"{stem}_identification.tsv"
        report_path = out_dir / f"{stem}_qc_report.md"

        ExcelExporter.export(rows, xlsx_path)
        TabularExporter.export(rows, tsv_path)
        ReportExporter.export(rows, report_path)

        logger.info("Results exported successfully:")
        logger.info(f"  - Excel Report: {xlsx_path}")
        logger.info(f"  - Tabular TSV:  {tsv_path}")
        logger.info(f"  - Markdown QC:  {report_path}")

        _notify(f"Completed: {len(rows)} sequence(s) processed and exported.", 100.0)
        return rows
