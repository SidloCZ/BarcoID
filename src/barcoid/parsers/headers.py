"""
Delimiter-aware FASTA defline parser extracting specimen IDs, years, localities,
voucher codes, and preliminary morphological determinations.
"""

import re
from typing import Any, Dict, Optional

# Default prefix map for common ant genera (can be extended or overridden via config)
DEFAULT_GENUS_PREFIXES: Dict[str, str] = {
    "PHEI": "Pheidole",
    "HYPO": "Hypoponera",
    "POLY": "Polyrhachis",
    "CARE": "Carebara",
    "BRACH": "Brachymyrmex",
    "LEPT": "Leptogenys",
    "CREM": "Crematogaster",
    "CAMP": "Camponotus",
    "TETR": "Tetramorium",
    "STRO": "Strumigenys",
    "SOLE": "Solenopsis",
    "TAPI": "Tapinoma",
    "ACRO": "Acropyga",
    "ANOC": "Anochetus",
    "CARD": "Cardiocondyla",
    "COLO": "Colobopsis",
    "DIAC": "Diacamma",
    "ECTO": "Ectomomyrmex",
    "LEPI": "Lepisiota",
    "MONO": "Monomorium",
    "MYRM": "Myrmicaria",
    "OECO": "Oecophylla",
    "ODON": "Odontomachus",
    "NYLA": "Nylanderia",
    "PARA": "Paratrechina",
    "PLAG": "Plagiolepis",
    "PRIS": "Pristomyrmex",
    "PSEU": "Pseudolasius",
    "TECH": "Technomyrmex",
}

DEFAULT_KNOWN_GENERA = {
    "Pheidole", "Hypoponera", "Polyrhachis", "Carebara", "Brachymyrmex", "Leptogenys",
    "Crematogaster", "Camponotus", "Tetramorium", "Strumigenys", "Solenopsis", "Tapinoma",
    "Acropyga", "Anochetus", "Cardiocondyla", "Colobopsis", "Diacamma", "Ectomomyrmex",
    "Lepisiota", "Monomorium", "Myrmicaria", "Oecophylla", "Odontomachus", "Nylanderia",
    "Paratrechina", "Plagiolepis", "Pristomyrmex", "Pseudolasius", "Technomyrmex",
    "Brachyponera", "Ponera", "Mesoponera", "Platythyrea", "Gnamptogenys", "Rhytidoponera",
    "Leptomyrmex", "Iridomyrmex", "Ochetellus", "Dolichoderus", "Bothriomyrmex"
}


class HeaderParser:
    """Parses FASTA deflines using delimiter-aware tokenization."""

    def __init__(self, custom_prefix_map: Optional[Dict[str, str]] = None):
        self.prefix_map = dict(DEFAULT_GENUS_PREFIXES)
        if custom_prefix_map:
            self.prefix_map.update(custom_prefix_map)

    def parse_header(self, header: str) -> Dict[str, Any]:
        """
        Parses a FASTA header string into structured specimen metadata.
        """
        clean_hdr = header.lstrip(">").strip()
        parts = clean_hdr.split(";")
        main_id = parts[0]

        # Extract standard sample ID: e.g. MJB0001426_MJB016_redo3 or general SampleID
        m_sample = re.search(r"(MJB\d{7}_MJB\d{3}(?:_redo\d*)?)", main_id)
        if m_sample:
            sample_id = m_sample.group(1)
            suffix = main_id[m_sample.end():].lstrip("_")
        else:
            tokens = main_id.split("_")
            if len(tokens) > 1:
                sample_id = tokens[0]
                suffix = "_".join(tokens[1:])
            else:
                sample_id = main_id
                suffix = ""

        # Determine plate name: match _MJBxxx (ignoring leading specimen MJB000xxxx)
        m_plate = re.search(r"_(MJB\d{3}(?:_redo\d*)?)", sample_id)
        plate = m_plate.group(1) if m_plate else "Unknown"

        # Delimiter-aware Year extraction (e.g. _2017_ or _2004_)
        m_year = re.search(r"(?:^|_)(19\d{2}|20\d{2})(?:_|$)", suffix)
        year = m_year.group(1) if m_year else ""

        field_morpho_code = ""
        field_inferred_genus = ""
        locality = ""
        voucher_code = ""

        if suffix:
            has_double_underscore = "__" in suffix
            tokens = [t for t in suffix.split("_") if t]

            found_genus = None
            morpho_token = None

            for t in tokens:
                for g in DEFAULT_KNOWN_GENERA:
                    if t.lower() == g.lower():
                        found_genus = g
                        morpho_token = t
                        break
                if found_genus:
                    break

                m_code = re.match(r"^([A-Z]{3,5})(\d+)$", t, re.IGNORECASE)
                if m_code:
                    prefix = m_code.group(1).upper()
                    if prefix in self.prefix_map:
                        found_genus = self.prefix_map[prefix]
                        morpho_token = t
                        break

            if found_genus:
                field_inferred_genus = found_genus
                field_morpho_code = morpho_token
            elif has_double_underscore:
                field_morpho_code = ""
                field_inferred_genus = ""

            # Voucher detection (e.g., GUA0444, MJ19435, field_3002, WE3.P8D...)
            v_matches = re.findall(r"(?:GUA\d+|MJ\d+|field_\d+|WE[\w\.]+|\b\d{2,4}\b)", suffix)
            if v_matches:
                v_candidates = [v for v in v_matches if v != year]
                voucher_code = v_candidates[-1] if v_candidates else ""

            # Locality is remaining text after removing year, morpho, and voucher tokens
            rem = suffix
            if year:
                rem = re.sub(r"(?:^|_)" + re.escape(year) + r"(?:_|$)", "_", rem)
            if morpho_token:
                rem = rem.replace(morpho_token, "")
            if voucher_code:
                rem = rem.replace(voucher_code, "")
            locality = re.sub(r"_+", " ", rem).strip()

        return {
            "full_header": header,
            "clean_id": main_id,
            "sample_id": sample_id,
            "plate": plate,
            "year": year,
            "locality": locality,
            "field_morpho_code": field_morpho_code,
            "field_inferred_genus": field_inferred_genus,
            "voucher_code": voucher_code,
            "raw_suffix": suffix,
        }
