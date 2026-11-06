"""
Command-line interface for BarcoID.
"""

import argparse
import sys
from pathlib import Path
from barcoid import __version__
from barcoid.config import BarcoIDConfig


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
        "-i", "--input",
        dest="input_fasta",
        type=Path,
        help="Path to input FASTA file containing query DNA barcodes.",
    )
    parser.add_argument(
        "-m", "--metadata",
        dest="metadata_file",
        type=Path,
        help="Optional external CSV/TSV metadata sheet linking vouchers to morphological IDs.",
    )
    parser.add_argument(
        "-o", "--output-dir",
        dest="output_dir",
        type=Path,
        default=Path("results"),
        help="Directory to save generated Excel and tabular identification reports.",
    )
    parser.add_argument(
        "--cache-dir",
        dest="cache_dir",
        type=Path,
        default=Path(".id_cache"),
        help="Directory storing persistent JSON API query cache.",
    )
    parser.add_argument(
        "--taxon",
        dest="taxon",
        type=str,
        default="Formicidae",
        help="Target taxon filter for NCBI BLAST queries (e.g., 'Formicidae', 'Insecta', 'Hymenoptera').",
    )
    parser.add_argument(
        "--local-blast-db",
        dest="local_blast_db",
        type=Path,
        help="Optional path to local BLAST nucleotide database (bypasses remote QBLAST).",
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
    return parser


def main(args=None):
    """Entry point for the BarcoID CLI."""
    parser = build_parser()
    parsed_args = parser.parse_args(args)

    if not parsed_args.input_fasta:
        parser.print_help()
        sys.exit(1)

    print(f"BarcoID v{__version__} starting...")
    print(f"Input FASTA: {parsed_args.input_fasta}")
    print(f"Output Directory: {parsed_args.output_dir}")
    print(f"Target Taxon: {parsed_args.taxon}")


if __name__ == "__main__":
    main()
