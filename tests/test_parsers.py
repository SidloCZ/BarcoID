"""
Unit tests for BarcoID sequence and header parsers.
"""

import tempfile
import unittest
from pathlib import Path

from barcoid.parsers.fasta import FastaParser
from barcoid.parsers.headers import HeaderParser
from barcoid.parsers.metadata import MetadataParser
from barcoid.parsers.ontbarcoder import OntbarcoderParser


class TestParsers(unittest.TestCase):
    """Verifies FASTA reading, defline tokenization, and metadata joins."""

    def test_header_parser_ant_code(self):
        parser = HeaderParser()
        header = ">MJB0001426_MJB016_redo3_Valavahalo_2017_PHEI01_GUA0444;313;41;ambs=0;estgaps=0"
        parsed = parser.parse_header(header)

        self.assertEqual(parsed["sample_id"], "MJB0001426_MJB016_redo3")
        self.assertEqual(parsed["plate"], "MJB016_redo3")
        self.assertEqual(parsed["year"], "2017")
        self.assertEqual(parsed["field_morpho_code"], "PHEI01")
        self.assertEqual(parsed["field_inferred_genus"], "Pheidole")
        self.assertEqual(parsed["voucher_code"], "GUA0444")
        self.assertIn("Valavahalo", parsed["locality"])

    def test_header_parser_unassigned_morphospecies(self):
        parser = HeaderParser()
        header = ">MJB0001430_MJB016_redo3_Valavahalo__GUA0448"
        parsed = parser.parse_header(header)

        self.assertEqual(parsed["sample_id"], "MJB0001430_MJB016_redo3")
        self.assertEqual(parsed["field_morpho_code"], "")
        self.assertEqual(parsed["field_inferred_genus"], "")
        self.assertEqual(parsed["voucher_code"], "GUA0448")

    def test_ontbarcoder_parser(self):
        header = ">Sample1;658;45;ambs=2;estgaps=0"
        stats = OntbarcoderParser.parse_stats(header)
        self.assertEqual(stats["seq_length"], 658)
        self.assertEqual(stats["coverage"], 45)
        self.assertEqual(stats["ambiguities"], 2)
        self.assertEqual(stats["est_gaps"], 0)

    def test_fasta_parser_with_capping(self):
        with tempfile.NamedTemporaryFile("w", suffix=".fasta", delete=False) as f:
            for i in range(10):
                f.write(f">Seq_{i}\nATCGATCGATCG\n")
            f_path = Path(f.name)

        try:
            # Test capping at 3 sequences
            capped = FastaParser.read_sequences(f_path, max_sequences=3)
            self.assertEqual(len(capped), 3)

            # Test reading all sequences
            all_seqs = FastaParser.read_sequences(f_path)
            self.assertEqual(len(all_seqs), 10)

            stats = FastaParser.compute_summary_stats(all_seqs)
            self.assertEqual(stats["count"], 10)
            self.assertEqual(stats["mean_len"], 12.0)
        finally:
            f_path.unlink(missing_ok=True)

    def test_metadata_parser(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("sample_id,field_morphospecies,field_genus\n")
            f.write("SAMPLE_01,Camponotus ligniperda,Camponotus\n")
            f.write("SAMPLE_02,Lasius niger,Lasius\n")
            f_path = Path(f.name)

        try:
            meta = MetadataParser(f_path, sample_col="sample_id", morpho_col="field_morphospecies")
            record1 = meta.get_metadata("SAMPLE_01")
            self.assertIsNotNone(record1)
            self.assertEqual(record1["field_morpho_code"], "Camponotus ligniperda")
            self.assertEqual(record1["field_inferred_genus"], "Camponotus")
        finally:
            f_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
