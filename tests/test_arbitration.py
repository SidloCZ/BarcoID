"""
Unit tests for concordance scoring and quality control discrepancy detection.
"""

import unittest

from barcoid.arbitration.concordance import ConcordanceEngine
from barcoid.arbitration.qc import QcAuditor
from barcoid.config import BarcoIDConfig


class TestArbitration(unittest.TestCase):
    """Verifies concordance status classification and QC flags."""

    def setUp(self):
        self.config = BarcoIDConfig()
        self.concordance = ConcordanceEngine(self.config)
        self.qc = QcAuditor(self.config)

    def test_concordant_assignment(self):
        field_genus = "Pheidole"
        bold_res = {
            "top_genus": "Pheidole",
            "top_species": "Pheidole oceanica",
            "top_pct_identity": 99.2,
        }
        ncbi_res = {
            "top_genus": "Pheidole",
            "top_species": "Pheidole oceanica",
            "top_pct_identity": 99.0,
        }
        gbif_res = {"canonicalName": "Pheidole oceanica", "status": "ACCEPTED"}

        c_genus, c_species, status, conf = self.concordance.evaluate(
            field_genus, bold_res, ncbi_res, gbif_res
        )
        qc_flag = self.qc.audit(field_genus, bold_res, ncbi_res, status)

        self.assertEqual(c_genus, "Pheidole")
        self.assertEqual(c_species, "Pheidole oceanica")
        self.assertEqual(status, "CONCORDANT")
        self.assertEqual(qc_flag, "OK")

    def test_new_assignment(self):
        field_genus = ""  # Unidentified field specimen
        bold_res = {
            "top_genus": "Hypoponera",
            "top_species": "Hypoponera sp.",
            "top_pct_identity": 98.5,
        }
        ncbi_res = {
            "top_genus": "Hypoponera",
            "top_species": "Hypoponera sp.",
            "top_pct_identity": 98.2,
        }
        gbif_res = {"canonicalName": "Hypoponera", "status": "ACCEPTED"}

        c_genus, c_species, status, conf = self.concordance.evaluate(
            field_genus, bold_res, ncbi_res, gbif_res
        )
        qc_flag = self.qc.audit(field_genus, bold_res, ncbi_res, status)

        self.assertEqual(c_genus, "Hypoponera")
        self.assertEqual(status, "NEW_ASSIGNMENT")
        self.assertEqual(qc_flag, "OK")

    def test_mismatch_alert_cross_genus(self):
        field_genus = "Technomyrmex"  # Field labeled Technomyrmex
        # Sequences match Pheidole with high identity -> cross-well swap / contamination suspect
        bold_res = {
            "top_genus": "Pheidole",
            "top_species": "Pheidole oceanica",
            "top_pct_identity": 97.5,
        }
        ncbi_res = {
            "top_genus": "Pheidole",
            "top_species": "Pheidole oceanica",
            "top_pct_identity": 97.2,
        }
        gbif_res = {"canonicalName": "Pheidole oceanica", "status": "ACCEPTED"}

        c_genus, c_species, status, conf = self.concordance.evaluate(
            field_genus, bold_res, ncbi_res, gbif_res
        )
        qc_flag = self.qc.audit(field_genus, bold_res, ncbi_res, status)

        self.assertEqual(status, "MISMATCH_ALERT")
        self.assertEqual(qc_flag, "CONTAMINATION_SUSPECT")

    def test_human_contamination(self):
        field_genus = "Pheidole"
        bold_res = {"top_genus": "Homo", "top_species": "Homo sapiens", "top_pct_identity": 100.0}
        ncbi_res = {"top_genus": "Homo", "top_species": "Homo sapiens", "top_pct_identity": 100.0}
        gbif_res = {"canonicalName": "Homo sapiens", "status": "ACCEPTED"}

        c_genus, c_species, status, conf = self.concordance.evaluate(
            field_genus, bold_res, ncbi_res, gbif_res
        )
        qc_flag = self.qc.audit(field_genus, bold_res, ncbi_res, status)

        self.assertEqual(qc_flag, "CONTAMINATION_HUMAN")

    def test_database_conflict(self):
        field_genus = ""
        bold_res = {
            "top_genus": "Camponotus",
            "top_species": "Camponotus sp.",
            "top_pct_identity": 98.0,
        }
        ncbi_res = {
            "top_genus": "Colobopsis",
            "top_species": "Colobopsis sp.",
            "top_pct_identity": 98.0,
        }
        gbif_res = {}

        c_genus, c_species, status, conf = self.concordance.evaluate(
            field_genus, bold_res, ncbi_res, gbif_res
        )
        qc_flag = self.qc.audit(field_genus, bold_res, ncbi_res, status)

        self.assertEqual(status, "MISMATCH_ALERT")
        self.assertEqual(qc_flag, "DATABASE_CONFLICT")


if __name__ == "__main__":
    unittest.main()
