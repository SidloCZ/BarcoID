"""
Command-line interface and dual GUI/CLI launcher for BarcoID.
"""

import argparse
import logging
import sys
from pathlib import Path

from barcoid import __version__
from barcoid.config import BarcoIDConfig
from barcoid.pipeline import BarcoIDPipeline


def configure_logging(verbose: bool = False):
    """Sets up console logging formatting."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def build_parser() -> argparse.ArgumentParser:
    """Constructs the command-line argument parser for BarcoID."""
    parser = argparse.ArgumentParser(
        prog="barcoid",
        description="BarcoID: Multi-Source DNA Barcode Taxonomic Identifier, Cross-Referencer & QC Auditor",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--gui",
        dest="gui",
        action="store_true",
        help="Launch the standalone BarcoID Desktop GUI window (default when run with no arguments).",
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_fasta",
        type=Path,
        required=False,
        help="Path to input FASTA file containing query DNA barcodes.",
    )
    parser.add_argument(
        "-m",
        "--metadata",
        dest="metadata_file",
        type=Path,
        help="Optional external CSV/TSV/XLSX metadata sheet linking vouchers to morphological IDs.",
    )
    parser.add_argument(
        "--sample-col",
        dest="sample_col",
        type=str,
        default="sample_id",
        help="Column name in external metadata sheet for sample/voucher ID (default: 'sample_id').",
    )
    parser.add_argument(
        "--morpho-col",
        dest="morpho_col",
        type=str,
        default="field_morphospecies",
        help="Column name in external metadata sheet for morphological taxon (default: 'field_morphospecies').",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=Path("results"),
        help="Directory to save generated Excel, TSV, and Markdown reports (default: 'results').",
    )
    parser.add_argument(
        "--cache-dir",
        dest="cache_dir",
        type=Path,
        default=Path(".id_cache"),
        help="Directory storing persistent JSON API query cache (default: '.id_cache').",
    )
    parser.add_argument(
        "--max-sequences",
        dest="max_sequences",
        type=int,
        help="Safety cap: Maximum number of sequences to process (e.g. 20 or 50 for pilot testing).",
    )
    parser.add_argument(
        "--request-delay",
        dest="request_delay",
        type=float,
        default=2.0,
        help="Pacing delay (in seconds) between remote network batches (default: 2.0s).",
    )
    parser.add_argument(
        "--bold-batch-size",
        dest="bold_batch_size",
        type=int,
        default=25,
        help="Batch size for BOLD Systems v5 submissions (default: 25).",
    )
    parser.add_argument(
        "--ncbi-batch-size",
        dest="ncbi_batch_size",
        type=int,
        default=5,
        help="Batch size for remote NCBI QBLAST submissions (default: 5).",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Inspect sequences and cache without making any remote network calls.",
    )
    parser.add_argument(
        "--force-refresh",
        dest="force_refresh",
        action="store_true",
        help="Bypass disk cache and force re-querying external APIs.",
    )
    parser.add_argument(
        "--taxon",
        dest="taxon",
        type=str,
        default="Formicidae",
        help="Target taxon filter for NCBI BLAST queries (default: 'Formicidae').",
    )
    parser.add_argument(
        "--local-blast-db",
        dest="local_blast_db",
        type=Path,
        help="Optional path to indexed local BLAST nucleotide database (bypasses remote QBLAST).",
    )
    parser.add_argument(
        "--ncbi-email",
        dest="ncbi_email",
        type=str,
        help="NCBI user email for Entrez/QBLAST rate compliance.",
    )
    parser.add_argument(
        "--ncbi-api-key",
        dest="ncbi_api_key",
        type=str,
        help="NCBI API key to unlock higher request limits (10 req/s).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        action="store_true",
        help="Enable detailed debug logging.",
    )
    return parser


def main(args=None):
    """Entry point for the BarcoID CLI and Desktop GUI."""
    effective_args = sys.argv[1:] if args is None else list(args)

    # If double-clicked or launched without arguments, open the Desktop GUI
    if len(effective_args) == 0:
        from barcoid.gui import launch_gui

        launch_gui()
        return

    parser = build_parser()
    parsed_args = parser.parse_args(effective_args)

    if parsed_args.gui:
        from barcoid.gui import launch_gui

        launch_gui()
        return

    if not parsed_args.input_fasta:
        parser.error(
            "the following arguments are required in CLI mode: -i/--input (or run with no arguments to open GUI)"
        )

    configure_logging(verbose=parsed_args.verbose)

    config = BarcoIDConfig(
        cache_dir=parsed_args.cache_dir,
        output_dir=parsed_args.output_dir,
        max_sequences=parsed_args.max_sequences,
        request_delay=parsed_args.request_delay,
        bold_batch_size=parsed_args.bold_batch_size,
        ncbi_batch_size=parsed_args.ncbi_batch_size,
        dry_run=parsed_args.dry_run,
        force_refresh=parsed_args.force_refresh,
        local_blast_db=parsed_args.local_blast_db,
        ncbi_email=parsed_args.ncbi_email,
        ncbi_api_key=parsed_args.ncbi_api_key,
    )

    if parsed_args.taxon:
        config.ncbi_entrez_query = f"{parsed_args.taxon}[Organism:exp]"

    pipeline = BarcoIDPipeline(config)
    try:
        pipeline.run(
            fasta_path=parsed_args.input_fasta,
            metadata_path=parsed_args.metadata_file,
            sample_col=parsed_args.sample_col,
            morpho_col=parsed_args.morpho_col,
        )
    except Exception as exc:
        logging.error(f"Execution failed: {exc}")
        if parsed_args.verbose:
            logging.exception(exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
