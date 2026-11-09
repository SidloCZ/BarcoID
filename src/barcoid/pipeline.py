"""
Master pipeline orchestrator for BarcoID with progressive chunking and multi-engine execution.
"""

import inspect
import logging
import time
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
        progress_callback: Optional[Callable[..., None]] = None,
        service_callback: Optional[Callable[[str, str], None]] = None,
        preliminary_callback: Optional[
            Callable[[List[Dict[str, Any]], Optional[Path]], None]
        ] = None,
    ) -> List[Dict[str, Any]]:
        """Executes the multi-source pipeline end-to-end with progressive chunking and ETA tracking."""

        def _notify(stage: str, pct: float, metrics: Optional[Dict[str, Any]] = None):
            if progress_callback:
                try:
                    sig = inspect.signature(progress_callback)
                    if len(sig.parameters) >= 3:
                        progress_callback(stage, pct, metrics)
                    else:
                        progress_callback(stage, pct)
                except Exception:
                    try:
                        progress_callback(stage, pct, metrics)
                    except TypeError:
                        progress_callback(stage, pct)

        def _srv(name: str, status: str):
            if service_callback:
                try:
                    service_callback(name, status)
                except Exception:
                    pass

        _srv("morpho", "Active")
        _notify("Parsing FASTA sequences and metadata...", 10.0)

        # 1. Parse input FASTA
        sequences = FastaParser.read_sequences(fasta_path, max_sequences=self.config.max_sequences)
        if not sequences:
            logger.warning(f"No valid sequences found in {fasta_path}.")
            _notify("No sequences found.", 100.0)
            return []

        logger.info(f"Loaded {len(sequences)} sequence(s) from {fasta_path.name}")

        # 2. Parse optional metadata sheet
        meta_parser = None
        if metadata_path and Path(metadata_path).exists():
            meta_parser = MetadataParser(
                metadata_path=Path(metadata_path),
                sample_col=sample_col,
                morpho_col=morpho_col,
            )
            logger.info(
                f"Loaded {len(meta_parser.records)} metadata record(s) from {Path(metadata_path).name}"
            )

        # Pre-parse headers & metadata so morphological priors are ready immediately
        parsed_by_hdr: Dict[str, Dict[str, Any]] = {}
        initial_gbif_names: List[str] = []
        for hdr, _ in sequences:
            p_meta = self.header_parser.parse_header(hdr)
            p_meta.update(self.ont_parser.parse_stats(hdr))
            if meta_parser:
                ext_meta = (
                    meta_parser.get_metadata(p_meta.get("sample_id", ""))
                    or meta_parser.get_metadata(p_meta.get("clean_id", ""))
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

        # 4. Progressive Chunking & Concurrent Multi-Engine Execution
        _srv("bold", "Active")
        _srv("gbif", "Active")
        if self.config.skip_ncbi:
            _srv("ncbi", "Skipped")
        else:
            _srv("ncbi", "Active")

        gbif_engine = GbifEngine(self.config, self.cache_manager)
        bold_engine = BoldEngine(self.config, self.cache_manager)
        blast_engine = None
        if not self.config.skip_ncbi:
            if self.config.local_blast_db and Path(self.config.local_blast_db).exists():
                blast_engine = LocalBlastEngine(self.config, self.cache_manager)
            else:
                blast_engine = RemoteBlastEngine(self.config, self.cache_manager)

        # Pre-resolve initial morphological genera with GBIF
        if initial_gbif_names:
            gbif_engine.match_batch(list(set(initial_gbif_names)))

        total_sequences = len(sequences)
        chunk_size = max(1, self.config.preliminary_interval)
        total_chunks = (total_sequences + chunk_size - 1) // chunk_size

        out_dir = Path(self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(fasta_path).stem
        prelim_xlsx_path = out_dir / f"{stem}_preliminary.xlsx"

        start_time = time.time()
        rows: List[Dict[str, Any]] = []

        for chunk_idx, chunk_start in enumerate(range(0, total_sequences, chunk_size)):
            chunk_seqs = sequences[chunk_start : chunk_start + chunk_size]
            chunk_num = chunk_idx + 1

            def _run_chunk_bold(seqs=chunk_seqs):
                return bold_engine.identify_sequences(seqs)

            def _run_chunk_ncbi(seqs=chunk_seqs):
                if blast_engine:
                    return blast_engine.identify_sequences(seqs)
                return {}

            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_bold = pool.submit(_run_chunk_bold)
                fut_ncbi = None if self.config.skip_ncbi else pool.submit(_run_chunk_ncbi)

                chunk_bold_res = fut_bold.result()
                chunk_ncbi_res = fut_ncbi.result() if fut_ncbi else {}

            # Collect newly discovered candidate names for GBIF
            chunk_candidates = []
            for hdr, _ in chunk_seqs:
                b_tax = chunk_bold_res.get(hdr, {}).get("top_species") or chunk_bold_res.get(
                    hdr, {}
                ).get("top_genus")
                n_tax = chunk_ncbi_res.get(hdr, {}).get("top_species") or chunk_ncbi_res.get(
                    hdr, {}
                ).get("top_genus")
                if b_tax:
                    chunk_candidates.append(b_tax)
                if n_tax:
                    chunk_candidates.append(n_tax)

            if chunk_candidates:
                gbif_engine.match_batch(list(set(chunk_candidates)))

            # Evaluate concordance & QC for this chunk
            for hdr, _ in chunk_seqs:
                parsed_meta = parsed_by_hdr[hdr]
                b_res = chunk_bold_res.get(hdr, {})
                n_res = chunk_ncbi_res.get(hdr, {})

                target_name = (
                    b_res.get("top_species")
                    or n_res.get("top_species")
                    or b_res.get("top_genus")
                    or ""
                )
                g_res = gbif_engine.match_species(target_name) if target_name else {}

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

            # Compute progress, speed, and ETA
            completed_count = len(rows)
            pct = round((completed_count / total_sequences) * 100.0, 1)
            elapsed = time.time() - start_time
            speed = completed_count / elapsed if elapsed > 0 else 0.0
            remaining_seqs = total_sequences - completed_count
            eta_seconds = (remaining_seqs / speed) if speed > 0 else 0.0

            eta_metrics = {
                "completed": completed_count,
                "total": total_sequences,
                "pct": pct,
                "elapsed_seconds": elapsed,
                "eta_seconds": eta_seconds,
                "speed": speed,
                "chunk": chunk_num,
                "total_chunks": total_chunks,
            }

            stage_msg = (
                f"Processed {completed_count}/{total_sequences} sequence(s) "
                f"(Chunk {chunk_num}/{total_chunks}, {speed:.1f} seq/s)"
            )
            _notify(stage_msg, pct, eta_metrics)

            # Progressive preliminary export if enabled
            if self.config.enable_preliminary_results and completed_count < total_sequences:
                try:
                    ExcelExporter.export(rows, prelim_xlsx_path)
                    if preliminary_callback:
                        preliminary_callback(list(rows), prelim_xlsx_path)
                except Exception as ex_err:
                    logger.warning(f"Could not export preliminary Excel: {ex_err}")
            elif preliminary_callback:
                preliminary_callback(list(rows), None)

            # Save dirty caches
            self.cache_manager.save()

        # All chunks completed
        _srv("bold", "Done")
        if not self.config.skip_ncbi:
            _srv("ncbi", "Done")
        _srv("gbif", "Done")

        # 5. Finalize cache and export outputs
        self.cache_manager.save()
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
