"""
Master pipeline orchestrator for BarcoID with concurrent multi-engine execution.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
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
        service_callback: Optional[Callable[[str, str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Executes the multi-source pipeline end-to-end with parallel engine queries."""

        def _notify(stage: str, pct: float):
            if progress_callback:
                try:
                    progress_callback(stage, pct)
                except Exception:
                    pass

        def _srv(name: str, status: str):
            if service_callback:
                try:
                    service_callback(name, status)
                except Exception:
                    pass

        _srv("morpho", "Active")
        _notify("Ingesting FASTA sequences and morphological metadata...", 10.0)

        # 1. Ingest sequences
        sequences = FastaParser.read_sequences(fasta_path, max_sequences=self.config.max_sequences)
        if not sequences:
            logger.warning("No sequences found in input file.")
            _srv("morpho", "Done")
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

        # Pre-parse headers & metadata so morphological priors are ready immediately
        parsed_by_hdr: Dict[str, Dict[str, Any]] = {}
        initial_gbif_names: List[str] = []
        for hdr, _ in sequences:
            p_meta = self.header_parser.parse_header(hdr)
            p_meta.update(self.ont_parser.parse_stats(hdr))
            if meta_parser:
                ext_meta = (
                    meta_parser.get_metadata(p_meta["sample_id"])
                    or meta_parser.get_metadata(p_meta["clean_id"])
                    or meta_parser.get_metadata(p_meta.get("voucher_code", ""))
                )
                if ext_meta:
                    if ext_meta.get("field_morpho_code"):
                        p_meta["field_morpho_code"] = ext_meta["field_morpho_code"]
                    if ext_meta.get("field_inferred_genus"):
                        p_meta["field_inferred_genus"] = ext_meta["field_inferred_genus"]
            parsed_by_hdr[hdr] = p_meta
            if p_meta.get("field_inferred_genus"):
                initial_gbif_names.append(p_meta["field_inferred_genus"])

        _srv("morpho", "Done")

        # 3. Workload safety audit
        uncached_bold = sum(1 for _, seq in sequences if not self.cache_manager.get_bold(seq))
        uncached_ncbi = (
            0
            if self.config.skip_ncbi
            else sum(1 for _, seq in sequences if not self.cache_manager.get_ncbi(seq))
        )
        if not self.config.skip_ncbi:
            warning = PacingAdvisor.audit_workload(
                uncached_ncbi,
                has_local_db=bool(
                    self.config.local_blast_db and Path(self.config.local_blast_db).exists()
                ),
            )
            if warning:
                logger.warning("=" * 70)
                logger.warning(warning)
                logger.warning("=" * 70)
        else:
            logger.info("NCBI BLAST engine skipped (--skip-ncbi enabled).")
            _srv("ncbi", "Skipped")

        if self.config.dry_run:
            logger.info(
                f"[Dry Run Summary] Total sequences: {len(sequences)}, "
                f"Uncached BOLD: {uncached_bold}, Uncached NCBI: {uncached_ncbi}"
            )
            _srv("bold", "Done")
            _srv("ncbi", "Skipped" if self.config.skip_ncbi else "Done")
            _srv("gbif", "Done")
            _notify(
                f"Dry run complete: {len(sequences)} sequence(s) inspected "
                f"({uncached_bold} uncached BOLD, {uncached_ncbi} uncached NCBI).",
                100.0,
            )
            return []

        # 4. Run BOLD, NCBI, and GBIF concurrently in parallel threads
        _srv("bold", "Active")
        _srv("gbif", "Active")
        if self.config.skip_ncbi:
            _srv("ncbi", "Skipped")
            _notify(
                f"Running BOLD ({len(sequences)} seqs) and GBIF in parallel (NCBI skipped)...",
                35.0,
            )
        else:
            _srv("ncbi", "Active")
            _notify(
                f"Running BOLD ({len(sequences)} seqs), NCBI BLAST ({len(sequences)} seqs), and GBIF in parallel...",
                35.0,
            )

        gbif_engine = GbifEngine(self.config, self.cache_manager)

        def _run_bold() -> Dict[str, Dict[str, Any]]:
            bold_engine = BoldEngine(self.config, self.cache_manager)
            res = bold_engine.identify_sequences(sequences)
            _srv("bold", "Done")
            return res

        def _run_ncbi() -> Dict[str, Dict[str, Any]]:
            if self.config.local_blast_db and Path(self.config.local_blast_db).exists():
                blast_engine = LocalBlastEngine(self.config, self.cache_manager)
                res = blast_engine.identify_sequences(sequences)
            else:
                remote_engine = RemoteBlastEngine(self.config, self.cache_manager)
                res = remote_engine.identify_sequences(sequences)
            _srv("ncbi", "Done")
            return res

        def _run_initial_gbif() -> Dict[str, Dict[str, Any]]:
            if not initial_gbif_names:
                return {}
            return gbif_engine.match_batch(list(set(initial_gbif_names)))

        with ThreadPoolExecutor(max_workers=3) as pool:
            fut_bold = pool.submit(_run_bold)
            fut_ncbi = None if self.config.skip_ncbi else pool.submit(_run_ncbi)
            fut_gbif_init = pool.submit(_run_initial_gbif)

            gbif_results = fut_gbif_init.result()
            bold_results = fut_bold.result()
            if fut_ncbi is not None:
                _notify("BOLD finished; awaiting remaining parallel streams...", 65.0)
                ncbi_results = fut_ncbi.result()
            else:
                ncbi_results = {}
                _notify("BOLD and initial GBIF finished.", 65.0)

        # 5. Resolve any newly discovered candidate names from BOLD and NCBI hits via GBIF
        _notify("Finalizing GBIF Taxonomic Backbone harmonization...", 82.0)
        candidate_names = []
        for hdr, _ in sequences:
            b_tax = bold_results.get(hdr, {}).get("top_species") or bold_results.get(hdr, {}).get(
                "top_genus"
            )
            n_tax = ncbi_results.get(hdr, {}).get("top_species") or ncbi_results.get(hdr, {}).get(
                "top_genus"
            )
            if b_tax and b_tax not in gbif_results:
                candidate_names.append(b_tax)
            if n_tax and n_tax not in gbif_results:
                candidate_names.append(n_tax)

        if candidate_names:
            gbif_results.update(gbif_engine.match_batch(list(set(candidate_names))))
        _srv("gbif", "Done")

        # 6. Synthesize metadata, evaluate concordance, and run QC
        _notify("Computing Concordance Matrix & exporting reports...", 92.0)
        rows: List[Dict[str, Any]] = []
        for hdr, _ in sequences:
            parsed_meta = parsed_by_hdr[hdr]
            b_res = bold_results.get(hdr, {})
            n_res = ncbi_results.get(hdr, {})

            target_name = (
                b_res.get("top_species") or n_res.get("top_species") or b_res.get("top_genus") or ""
            )
            g_res = gbif_results.get(target_name, {})

            c_genus, c_species, status, conf = self.concordance_engine.evaluate(
                parsed_meta["field_inferred_genus"], b_res, n_res, g_res
            )
            qc_flag = self.qc_auditor.audit(
                parsed_meta["field_inferred_genus"], b_res, n_res, status
            )

            rows.append(
                {
                    "meta": parsed_meta,
                    "bold": b_res,
                    "ncbi": n_res,
                    "gbif": g_res,
                    "consensus_genus": c_genus,
                    "consensus_species": c_species,
                    "concordance_status": status,
                    "confidence_score": conf,
                    "qc_flag": qc_flag,
                }
            )

        # 7. Finalize cache and export outputs
        self.cache_manager.save()
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
