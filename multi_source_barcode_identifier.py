#!/usr/bin/env python3
"""
scripts/multi_source_barcode_identifier.py

Automated Multi-Source DNA Barcode Taxonomic Identification & Comparison Pipeline.
Cross-references recovered Oxford Nanopore DNA barcodes against 4 distinct evidence sources:
  1. FASTA Header Suffix (Field locality, collection year, morphological morphospecies ID, voucher code)
  2. BOLD Systems v5 ID Engine (REST API submission & polling, retrieving percent identity, BIN URIs, and full lineage)
  3. NCBI BLAST (Remote QBLAST against GenBank nt, restricted to Formicidae / Hymenoptera)
  4. GBIF Taxonomic Backbone (REST API verification, accepted status, and optional Sequence-ID CSV ingestion)

Generates a unified, formatted multi-tab Excel workbook (.xlsx) comparing all 4 sources side-by-side,
with automated concordance scoring and QC discrepancy flagging.
"""

import argparse
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
import requests
from Bio import SeqIO
from Bio.Blast import NCBIXML
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# Common Formicidae genus code prefixes frequently used in field morphospecies codes
KNOWN_GENUS_PREFIXES = {
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

KNOWN_GENUS_NAMES = {
    "Pheidole",
    "Hypoponera",
    "Polyrhachis",
    "Carebara",
    "Brachymyrmex",
    "Leptogenys",
    "Crematogaster",
    "Camponotus",
    "Tetramorium",
    "Strumigenys",
    "Solenopsis",
    "Tapinoma",
    "Acropyga",
    "Anochetus",
    "Cardiocondyla",
    "Colobopsis",
    "Diacamma",
    "Ectomomyrmex",
    "Lepisiota",
    "Monomorium",
    "Myrmicaria",
    "Oecophylla",
    "Odontomachus",
    "Nylanderia",
    "Paratrechina",
    "Plagiolepis",
    "Pristomyrmex",
    "Pseudolasius",
    "Technomyrmex",
    "Brachyponera",
    "Ponera",
    "Mesoponera",
    "Platythyrea",
    "Gnamptogenys",
    "Rhytidoponera",
    "Leptomyrmex",
    "Iridomyrmex",
    "Ochetellus",
    "Dolichoderus",
    "Bothriomyrmex",
}


def parse_header_suffix(header: str) -> Dict[str, Any]:
    """
    Parses a FASTA header to extract sample ID, plate, ONTbarcoder statistics,
    and field metadata (locality, year, morphospecies code, voucher code).
    """
    clean_hdr = header.lstrip(">")
    parts = clean_hdr.split(";")
    main_id = parts[0]

    # Parse ONTbarcoder stats (e.g. ;313;41;ambs=0;estgaps=0)
    seq_len = 0
    coverage = 0
    ambs = 0
    estgaps = 0
    if len(parts) > 1 and parts[1].isdigit():
        seq_len = int(parts[1])
    if len(parts) > 2 and parts[2].isdigit():
        coverage = int(parts[2])
    for p in parts[3:]:
        if p.startswith("ambs="):
            try:
                ambs = int(p.split("=")[1])
            except ValueError:
                pass
        elif p.startswith("estgaps="):
            try:
                estgaps = int(p.split("=")[1])
            except ValueError:
                pass

    # Extract standard sample ID: e.g. MJB0001426_MJB016_redo3 or MJB0002756_MJB030
    m_sample = re.search(r"(MJB\d{7}_MJB\d{3}(?:_redo\d*)?)", main_id)
    if m_sample:
        sample_id = m_sample.group(1)
        suffix = main_id[m_sample.end() :].lstrip("_")
    else:
        sample_id = main_id
        suffix = ""

    # Determine plate name: match _MJBxxx (ignoring leading specimen MJB000xxxx)
    m_plate = re.search(r"_(MJB\d{3}(?:_redo\d*)?)", sample_id)
    plate = m_plate.group(1) if m_plate else "Unknown"

    # Extract Year (e.g., 2004, 2017, 2019)
    m_year = re.search(r"(?:^|_)(19\d{2}|20\d{2})(?:_|$)", suffix)
    year = m_year.group(1) if m_year else ""

    # Extract Field Morphospecies & Voucher
    field_morpho_code = ""
    field_inferred_genus = ""
    locality = ""
    voucher_code = ""

    if suffix:
        # Check for explicitly blank morphospecies (e.g. Valavahalo__GUA0124)
        has_double_underscore = "__" in suffix

        # Split tokens by underscore
        tokens = [t for t in suffix.split("_") if t]

        # Look for known genus name or prefix in tokens
        found_genus = None
        morpho_token = None

        for t in tokens:
            # Check full genus name
            for g in KNOWN_GENUS_NAMES:
                if t.lower() == g.lower():
                    found_genus = g
                    morpho_token = t
                    break
            if found_genus:
                break

            # Check prefix code like PHEI01, HYPO03
            m_code = re.match(r"^([A-Z]{3,5})(\d+)$", t, re.IGNORECASE)
            if m_code:
                prefix = m_code.group(1).upper()
                if prefix in KNOWN_GENUS_PREFIXES:
                    found_genus = KNOWN_GENUS_PREFIXES[prefix]
                    morpho_token = t
                    break

        if found_genus:
            field_inferred_genus = found_genus
            field_morpho_code = morpho_token
        elif has_double_underscore:
            field_morpho_code = ""
            field_inferred_genus = ""

        # Voucher detection (e.g., GUA0444, MJ19435, field_3002, 188, WE3.P8D...)
        v_matches = re.findall(r"(?:GUA\d+|MJ\d+|field_\d+|WE[\w\.]+|\b\d{2,4}\b)", suffix)
        if v_matches:
            # Filter out year if it was captured as voucher
            v_candidates = [v for v in v_matches if v != year]
            voucher_code = v_candidates[-1] if v_candidates else ""

        # Locality is remaining part after year, morpho, and voucher removal
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
        "seq_length": seq_len,
        "coverage": coverage,
        "ambiguities": ambs,
        "est_gaps": estgaps,
        "year": year,
        "locality": locality,
        "field_morpho_code": field_morpho_code,
        "field_inferred_genus": field_inferred_genus,
        "voucher_code": voucher_code,
        "raw_suffix": suffix,
    }


class CacheManager:
    """Manages persistent JSON caching on disk for web API queries."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.bold_cache_file = self.cache_dir / "bold_v5_cache.json"
        self.ncbi_cache_file = self.cache_dir / "ncbi_blast_cache.json"
        self.gbif_cache_file = self.cache_dir / "gbif_species_cache.json"

        self.bold_cache = self._load(self.bold_cache_file)
        self.ncbi_cache = self._load(self.ncbi_cache_file)
        self.gbif_cache = self._load(self.gbif_cache_file)

    def _load(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Warning] Failed to load cache {path}: {e}")
        return {}

    def save(self):
        with open(self.bold_cache_file, "w", encoding="utf-8") as f:
            json.dump(self.bold_cache, f, indent=2)
        with open(self.ncbi_cache_file, "w", encoding="utf-8") as f:
            json.dump(self.ncbi_cache, f, indent=2)
        with open(self.gbif_cache_file, "w", encoding="utf-8") as f:
            json.dump(self.gbif_cache, f, indent=2)


def query_bold_v5_batch(
    sequences: List[Tuple[str, str]],
    cache: Dict[str, Any],
    batch_size: int = 25,
    max_wait_seconds: int = 120,
) -> Dict[str, Dict[str, Any]]:
    """
    Submits batches of FASTA sequences to the BOLD Systems v5 ID engine via REST API,
    polls for completion, and returns structured identification results.
    """
    results = {}
    pending = []

    # Check cache first
    for hdr, seq in sequences:
        seq_hash = hashlib.sha256(seq.upper().encode()).hexdigest()
        if seq_hash in cache:
            results[hdr] = cache[seq_hash]
        else:
            pending.append((hdr, seq, seq_hash))

    if not pending:
        return results

    print(f"Submitting {len(pending)} sequence(s) to BOLD Systems v5 ID Engine...")
    base_url = "https://id.boldsystems.org/submission"
    params = {"db": "public.tax-derep", "mi": 0.94, "mo": 100, "maxh": 25, "order": 3}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Antigravity-BOLD-Client/1.0"
    }

    for i in range(0, len(pending), batch_size):
        chunk = pending[i : i + batch_size]
        fasta_lines = []
        for hdr, seq, _ in chunk:
            fasta_lines.append(f">{hdr}\n{seq}\n")
        fasta_body = "".join(fasta_lines)

        files = {"fasta_file": ("batch.fas", fasta_body, "text/plain")}

        try:
            resp = requests.post(base_url, params=params, files=files, headers=headers, timeout=60)
            if resp.status_code != 200:
                print(
                    f"[Error] BOLD submission failed with status {resp.status_code}: {resp.text[:200]}"
                )
                continue

            sub_data = resp.json()
            sub_id = sub_data.get("sub_id")
            if not sub_id:
                print(f"[Error] No sub_id in BOLD response: {sub_data}")
                continue

            poll_url = f"https://id.boldsystems.org/submission/results/{sub_id}"

            # Poll for results
            elapsed = 0
            poll_success = False
            while elapsed < max_wait_seconds:
                time.sleep(3)
                elapsed += 3
                r_poll = requests.get(poll_url, headers=headers, timeout=60)
                if r_poll.status_code == 200 and len(r_poll.text.strip()) > 0:
                    poll_success = True
                    # Process lines of JSON (one JSON per sequence)
                    for line in r_poll.text.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            seqid = record.get("seqid")
                            raw_hits = record.get("results", {})

                            # Parse hits
                            parsed_hits = []
                            for hit_key, hit_val in raw_hits.items():
                                key_parts = hit_key.split("|")
                                proc_id = key_parts[0] if len(key_parts) > 0 else ""
                                bin_uri = key_parts[2] if len(key_parts) > 2 else ""
                                pdist = hit_val.get("pdist", 100.0)
                                pident = 100.0 - pdist if pdist is not None else 0.0
                                tax = hit_val.get("taxonomy", {})

                                parsed_hits.append(
                                    {
                                        "process_id": proc_id,
                                        "bin_uri": bin_uri,
                                        "pct_identity": round(pident, 2),
                                        "bitscore": hit_val.get("bitscore", 0),
                                        "evalue": hit_val.get("evalue", None),
                                        "overlap": hit_val.get("overlap", 0),
                                        "mismatch": hit_val.get("mismatch", 0),
                                        "phylum": tax.get("phylum", ""),
                                        "class": tax.get("class", ""),
                                        "order": tax.get("order", ""),
                                        "family": tax.get("family", ""),
                                        "subfamily": tax.get("subfamily", ""),
                                        "genus": tax.get("genus", ""),
                                        "species": tax.get("species", ""),
                                    }
                                )

                            top_hit = parsed_hits[0] if parsed_hits else {}
                            top_genus = top_hit.get("genus", "")
                            top_species = top_hit.get("species", "")

                            # If species is blank in hit #1, check if nearby top hits in same genus provide a species designation
                            if not top_species and top_genus:
                                for h in parsed_hits[:5]:
                                    if h.get("genus") == top_genus and h.get("species"):
                                        top_species = h.get("species")
                                        break
                                if not top_species:
                                    top_species = f"{top_genus} sp."

                            res_obj = {
                                "has_match": bool(parsed_hits),
                                "hit_count": len(parsed_hits),
                                "top_genus": top_genus,
                                "top_species": top_species,
                                "top_pct_identity": top_hit.get("pct_identity", 0.0),
                                "top_bin": top_hit.get("bin_uri", ""),
                                "top_process_id": top_hit.get("process_id", ""),
                                "top_family": top_hit.get("family", ""),
                                "top_order": top_hit.get("order", ""),
                                "all_hits": parsed_hits,
                            }

                            # Cache by sequence hash
                            for h, _s, sh in chunk:
                                if h == seqid:
                                    cache[sh] = res_obj
                                    results[h] = res_obj
                                    break
                        except Exception as parse_err:
                            print(f"[Warning] Failed parsing BOLD result line: {parse_err}")
                    break

            if not poll_success:
                print(f"[Warning] Polling timed out for BOLD batch {sub_id}")

        except Exception as e:
            print(f"[Error] BOLD query error: {e}")

    return results


def qblast_xml(
    fasta_str: str,
    entrez_query: str = "txid36668[Organism:exp]",
    hitlist_size: int = 5,
    max_wait_seconds: int = 150,
    poll_interval: int = 6,
) -> Optional[str]:
    """
    Submits FASTA sequences to NCBI QBLAST with megablast and returns raw XML text.
    Times out gracefully if NCBI stalls instead of hanging indefinitely.
    """
    url = "https://blast.ncbi.nlm.nih.gov/Blast.cgi"
    put_params = {
        "CMD": "Put",
        "PROGRAM": "blastn",
        "DATABASE": "nt",
        "MEGABLAST": "on",
        "ENTREZ_QUERY": entrez_query,
        "HITLIST_SIZE": str(hitlist_size),
        "QUERY": fasta_str,
        "EMAIL": "barcoding_pipeline@example.com",
        "TOOL": "AntigravityBarcodeID",
    }

    try:
        r_put = requests.post(url, data=put_params, timeout=30)
        m_rid = re.search(r"RID = (\w+)", r_put.text)
        m_rtoe = re.search(r"RTOE = (\d+)", r_put.text)
        if not m_rid:
            print(f"  [Warning] Failed to obtain NCBI RID: {r_put.text[:200]}")
            return None

        rid = m_rid.group(1)
        rtoe = int(m_rtoe.group(1)) if m_rtoe else 15
        time.sleep(min(max(rtoe, 8), 25))

        elapsed = 0
        while elapsed < max_wait_seconds:
            poll_params = {"CMD": "Get", "FORMAT_OBJECT": "SearchInfo", "RID": rid}
            r_check = requests.get(url, params=poll_params, timeout=30)
            if "Status=WAITING" in r_check.text:
                time.sleep(poll_interval)
                elapsed += poll_interval
                continue
            elif "Status=FAILED" in r_check.text:
                print(f"  [Warning] NCBI Search {rid} failed on server.")
                return None
            elif "Status=UNKNOWN" in r_check.text:
                print(f"  [Warning] NCBI Search {rid} expired or unknown.")
                return None
            elif "Status=READY" in r_check.text:
                get_params = {"CMD": "Get", "FORMAT_TYPE": "XML", "RID": rid}
                r_xml = requests.get(url, params=get_params, timeout=60)
                return r_xml.text

        print(f"  [Warning] NCBI Search {rid} timed out after {max_wait_seconds}s.")
        return None
    except Exception as e:
        print(f"  [Warning] NCBI QBLAST request exception: {e}")
        return None


def query_ncbi_blast_batch(
    sequences: List[Tuple[str, str]],
    cache: Dict[str, Any],
    cache_mgr: Any,
    batch_size: int = 5,
    entrez_query: str = "txid36668[Organism:exp]",
    hitlist_size: int = 5,
    delay_between_batches: float = 3.0,
) -> Dict[str, Dict[str, Any]]:
    """
    Submits batches of DNA sequences to remote NCBI BLASTn (QBLAST) via Biopython.
    Uses clean query IDs (Q1, Q2, ...) to ensure 100% exact result mapping.
    Caches every result to disk immediately upon batch completion.
    """
    results = {}
    pending = []

    # Check cache first
    for hdr, seq in sequences:
        seq_hash = hashlib.sha256(seq.upper().encode()).hexdigest()
        if seq_hash in cache:
            results[hdr] = cache[seq_hash]
        else:
            pending.append((hdr, seq, seq_hash))

    if not pending:
        return results

    total_pending = len(pending)
    print(
        f"Submitting {total_pending} sequence(s) to remote NCBI BLASTn (batch size: {batch_size})..."
    )

    for b_idx in range(0, total_pending, batch_size):
        chunk = pending[b_idx : b_idx + batch_size]
        query_map = {}
        fasta_lines = []

        for q_num, (hdr, seq, seq_hash) in enumerate(chunk, start=1):
            qid = f"Q{q_num}"
            query_map[qid] = (hdr, seq_hash)
            fasta_lines.append(f">{qid}\n{seq}\n")

        chunk_fasta = "".join(fasta_lines)
        batch_num = (b_idx // batch_size) + 1
        total_batches = (total_pending + batch_size - 1) // batch_size
        print(
            f"  [Batch {batch_num}/{total_batches}] Querying NCBI for {len(chunk)} sequence(s)..."
        )

        try:
            xml_text = qblast_xml(
                chunk_fasta,
                entrez_query=entrez_query,
                hitlist_size=hitlist_size,
                max_wait_seconds=150,
            )
            if xml_text:
                records = list(NCBIXML.parse(io.StringIO(xml_text)))

                for rec in records:
                    # Extract clean QID from query string (e.g. 'Q1' or 'Q1 ')
                    qid = rec.query.split()[0] if rec.query else ""
                    if qid not in query_map:
                        continue
                    orig_hdr, orig_hash = query_map[qid]

                    hits = []
                    for alignment in rec.alignments:
                        hsp = alignment.hsps[0]
                        pct_id = (
                            (hsp.identities / hsp.align_length) * 100.0
                            if hsp.align_length > 0
                            else 0.0
                        )

                        # Extract genus/species from title
                        title = alignment.title
                        m_tax = re.search(
                            r">?gi\|\d+\|(?:gb|emb|dbj|tpg|ref)\|([\w\.]+)\|\s*(?:TPA(?:_asm)?:\s*)?([A-Za-z]+)\s+([A-Za-z0-9\.\_\-]+)",
                            title,
                        )
                        accession = alignment.accession
                        genus = ""
                        species = ""
                        if m_tax:
                            accession = m_tax.group(1)
                            genus = m_tax.group(2)
                            species = f"{m_tax.group(2)} {m_tax.group(3)}"
                        else:
                            words = title.split()
                            if len(words) > 1:
                                genus = words[1]

                        hits.append(
                            {
                                "title": title,
                                "accession": accession,
                                "genus": genus,
                                "species": species,
                                "pct_identity": round(pct_id, 2),
                                "align_length": hsp.align_length,
                                "evalue": float(hsp.expect),
                                "bitscore": float(hsp.bits),
                            }
                        )

                    top_hit = hits[0] if hits else {}
                    res_obj = {
                        "has_match": bool(hits),
                        "hit_count": len(hits),
                        "top_title": top_hit.get("title", ""),
                        "top_accession": top_hit.get("accession", ""),
                        "top_genus": top_hit.get("genus", ""),
                        "top_species": top_hit.get("species", ""),
                        "top_pct_identity": top_hit.get("pct_identity", 0.0),
                        "top_evalue": top_hit.get("evalue", None),
                        "top_bitscore": top_hit.get("bitscore", 0.0),
                        "all_hits": hits,
                    }

                    cache[orig_hash] = res_obj
                    results[orig_hdr] = res_obj
            else:
                print(
                    f"  [Warning] Batch {batch_num} returned no XML / timed out. Marking uncached as NO_MATCH."
                )
                for _qid, (orig_hdr, orig_hash) in query_map.items():
                    if orig_hash not in cache:
                        res_obj = {
                            "has_match": False,
                            "hit_count": 0,
                            "top_title": "",
                            "top_accession": "",
                            "top_genus": "",
                            "top_species": "",
                            "top_pct_identity": 0.0,
                            "top_evalue": None,
                            "top_bitscore": 0.0,
                            "all_hits": [],
                        }
                        cache[orig_hash] = res_obj
                        results[orig_hdr] = res_obj

            # Save cache to disk immediately after each batch
            cache_mgr.save()

            if b_idx + batch_size < total_pending:
                time.sleep(delay_between_batches)

        except Exception as e:
            print(f"  [Warning] Batch {batch_num} failed with error: {e}")
            for _qid, (orig_hdr, orig_hash) in query_map.items():
                if orig_hash not in cache:
                    res_obj = {
                        "has_match": False,
                        "hit_count": 0,
                        "top_title": "",
                        "top_accession": "",
                        "top_genus": "",
                        "top_species": "",
                        "top_pct_identity": 0.0,
                        "top_evalue": None,
                        "top_bitscore": 0.0,
                        "all_hits": [],
                    }
                    cache[orig_hash] = res_obj
                    results[orig_hdr] = res_obj
            cache_mgr.save()

    return results


def query_gbif_species_match(name: str, cache: Dict[str, Any]) -> Dict[str, Any]:
    """
    Standardizes a taxonomic name against the GBIF Taxonomic Backbone API.
    """
    if not name or name.strip() == "":
        return {}
    clean_name = name.strip()
    if clean_name in cache:
        return cache[clean_name]

    url = "https://api.gbif.org/v1/species/match"
    try:
        r = requests.get(url, params={"name": clean_name, "kingdom": "Animalia"}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            res = {
                "usageKey": data.get("usageKey"),
                "scientificName": data.get("scientificName", ""),
                "canonicalName": data.get("canonicalName", ""),
                "rank": data.get("rank", ""),
                "status": data.get("status", ""),
                "confidence": data.get("confidence", 0),
                "matchType": data.get("matchType", ""),
                "genus": data.get("genus", ""),
                "family": data.get("family", ""),
                "order": data.get("order", ""),
            }
            cache[clean_name] = res
            return res
    except Exception as e:
        print(f"[Warning] GBIF Species Match failed for '{name}': {e}")
    return {}


def determine_concordance(
    field_genus: str,
    bold_genus: str,
    ncbi_genus: str,
    gbif_genus: str,
    bold_pident: float,
    ncbi_pident: float,
) -> Tuple[str, str, str]:
    """
    Synthesizes genus assignments from the 4 sources and determines:
      1. Consensus genus
      2. Concordance Status (CONCORDANT, NEW_ASSIGNMENT, MISMATCH_ALERT, NO_MATCH)
      3. QC Flag (OK, LOW_IDENTITY, CONTAMINATION_SUSPECT)
    """
    # Determine consensus genus (prioritize sequence match agreement, then BOLD, NCBI, then Field)
    if bold_genus and ncbi_genus and bold_genus.lower() == ncbi_genus.lower():
        consensus = bold_genus
    elif bold_genus:
        consensus = bold_genus
    elif ncbi_genus:
        consensus = ncbi_genus
    elif field_genus:
        consensus = field_genus
    else:
        consensus = "Unassigned"

    max_pident = max(bold_pident, ncbi_pident)

    # Evaluate QC identity threshold
    is_low_id = 0.0 < max_pident < 95.0

    if not bold_genus and not ncbi_genus:
        qc_flag = "NO_DATA" if max_pident == 0.0 else "LOW_IDENTITY"
        return consensus, "NO_MATCH", qc_flag

    # Check agreement between field ID and sequence hits
    if field_genus:
        has_bold_mismatch = bold_genus and field_genus.lower() != bold_genus.lower()
        has_ncbi_mismatch = ncbi_genus and field_genus.lower() != ncbi_genus.lower()

        if has_bold_mismatch or has_ncbi_mismatch:
            status = "MISMATCH_ALERT"
            qc_flag = "CONTAMINATION_SUSPECT" if max_pident >= 95.0 else "LOW_IDENTITY_MISMATCH"
        else:
            status = "CONCORDANT"
            qc_flag = "LOW_IDENTITY" if is_low_id else "OK"
    else:
        # Field ID was unassigned (blank / __)
        has_db_mismatch = bold_genus and ncbi_genus and bold_genus.lower() != ncbi_genus.lower()
        if has_db_mismatch:
            status = "MISMATCH_ALERT"
            qc_flag = "DATABASE_CONFLICT"
        else:
            status = "NEW_ASSIGNMENT"
            qc_flag = "LOW_IDENTITY" if is_low_id else "OK"

    return consensus, status, qc_flag


def export_to_excel(rows: List[Dict[str, Any]], output_path: Path):
    """
    Writes a multi-tab, professionally formatted Excel workbook.
    """
    wb = openpyxl.Workbook()
    # Sheet 1: Master 4-way comparison
    ws_comp = wb.active
    ws_comp.title = "Taxonomic_Comparison"

    # Sheet 2: BOLD detailed hits
    ws_bold = wb.create_sheet(title="BOLD_Detailed_Hits")

    # Sheet 3: NCBI detailed hits
    ws_ncbi = wb.create_sheet(title="NCBI_Detailed_Hits")

    # Sheet 4: Discrepancies and QC
    ws_qc = wb.create_sheet(title="Discrepancies_and_QC")

    # Styles
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    fill_header = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    fill_qc_header = PatternFill(start_color="C00000", end_color="C00000", fill_type="solid")
    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    border_thin = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )

    # Master comparison columns
    comp_headers = [
        "Sample_ID",
        "Plate",
        "Seq_Len_bp",
        "Read_Coverage",
        "Ambiguities",
        # Source 1: Field Suffix
        "Field_Locality",
        "Field_Morpho_Code",
        "Field_Inferred_Genus",
        "Field_Voucher",
        # Source 2: BOLD Systems v5
        "BOLD_Top_Taxon",
        "BOLD_Genus",
        "BOLD_Pct_Identity",
        "BOLD_BIN_URI",
        "BOLD_Process_ID",
        # Source 3: NCBI BLAST
        "NCBI_Top_Taxon",
        "NCBI_Genus",
        "NCBI_Pct_Identity",
        "NCBI_Accession",
        "NCBI_Evalue",
        # Source 4: GBIF Backbone
        "GBIF_Canonical_Name",
        "GBIF_Rank",
        "GBIF_Confidence",
        "GBIF_Status",
        "GBIF_Taxon_ID",
        # Synthesis & Concordance
        "Consensus_Genus",
        "Concordance_Status",
        "QC_Flag",
        "Full_FASTA_Header",
    ]

    ws_comp.append(comp_headers)
    ws_qc.append(comp_headers)

    # Detailed BOLD headers (matching 313_boldigger.xlsx style)
    bold_headers = [
        "sample_id",
        "phylum",
        "class",
        "order",
        "family",
        "genus",
        "species",
        "pct_identity",
        "status",
        "BIN",
        "process_id",
        "bitscore",
        "overlap",
        "mismatch",
        "evalue",
    ]
    ws_bold.append(bold_headers)

    # Detailed NCBI headers
    ncbi_headers = [
        "sample_id",
        "accession",
        "genus",
        "species",
        "pct_identity",
        "align_length",
        "bitscore",
        "evalue",
        "title",
    ]
    ws_ncbi.append(ncbi_headers)

    # Populate rows
    for r in rows:
        meta = r["meta"]
        bold = r.get("bold", {})
        ncbi = r.get("ncbi", {})
        gbif = r.get("gbif", {})

        comp_row = [
            meta["sample_id"],
            meta["plate"],
            meta["seq_length"],
            meta["coverage"],
            meta["ambiguities"],
            meta["locality"],
            meta["field_morpho_code"],
            meta["field_inferred_genus"],
            meta["voucher_code"],
            bold.get("top_species") or bold.get("top_genus") or "",
            bold.get("top_genus", ""),
            bold.get("top_pct_identity", 0.0),
            bold.get("top_bin", ""),
            bold.get("top_process_id", ""),
            ncbi.get("top_species") or ncbi.get("top_genus") or "",
            ncbi.get("top_genus", ""),
            ncbi.get("top_pct_identity", 0.0),
            ncbi.get("top_accession", ""),
            str(ncbi.get("top_evalue", "")),
            gbif.get("canonicalName", ""),
            gbif.get("rank", ""),
            gbif.get("confidence", 0),
            gbif.get("status", ""),
            gbif.get("usageKey", ""),
            r["consensus_genus"],
            r["concordance_status"],
            r["qc_flag"],
            meta["full_header"],
        ]
        ws_comp.append(comp_row)

        if r["concordance_status"] == "MISMATCH_ALERT" or r["qc_flag"] != "OK":
            ws_qc.append(comp_row)

        # BOLD Detailed hits
        for bh in bold.get("all_hits", []):
            ws_bold.append(
                [
                    meta["sample_id"],
                    bh.get("phylum", ""),
                    bh.get("class", ""),
                    bh.get("order", ""),
                    bh.get("family", ""),
                    bh.get("genus", ""),
                    bh.get("species", ""),
                    bh.get("pct_identity", 0.0),
                    "public",
                    bh.get("bin_uri", ""),
                    bh.get("process_id", ""),
                    bh.get("bitscore", 0),
                    bh.get("overlap", 0),
                    bh.get("mismatch", 0),
                    str(bh.get("evalue", "")),
                ]
            )

        # NCBI Detailed hits
        for nh in ncbi.get("all_hits", []):
            ws_ncbi.append(
                [
                    meta["sample_id"],
                    nh.get("accession", ""),
                    nh.get("genus", ""),
                    nh.get("species", ""),
                    nh.get("pct_identity", 0.0),
                    nh.get("align_length", 0),
                    nh.get("bitscore", 0.0),
                    str(nh.get("evalue", "")),
                    nh.get("title", ""),
                ]
            )

    # Format sheets
    for ws, is_qc in [(ws_comp, False), (ws_qc, True), (ws_bold, False), (ws_ncbi, False)]:
        ws.freeze_panes = "A2"
        # Style header row
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = font_header
            cell.fill = fill_qc_header if is_qc else fill_header
            cell.alignment = align_center

        # Adjust column widths
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                cell.border = border_thin
                val_str = str(cell.value or "")
                if len(val_str) > max_len:
                    max_len = len(val_str)
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 10), 45)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    print(f"Successfully generated Excel workbook at: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Multi-Source DNA Barcode Taxonomic Identification & Comparison Pipeline"
    )
    parser.add_argument(
        "--input-fasta",
        type=str,
        default="Recovery_and_Decontamination_Outputs/recovered_consensus_barcodes/combined_results/Filtered_barcodes_1percamb_upto5err.fa",
        help="Path to input consensus barcodes FASTA file",
    )
    parser.add_argument(
        "--output-xlsx",
        type=str,
        default="Recovery_and_Decontamination_Outputs/rescued_barcodes_multi_source_identification.xlsx",
        help="Path to output Excel (.xlsx) file",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default="Recovery_and_Decontamination_Outputs/.id_cache",
        help="Directory to store API cache files",
    )
    parser.add_argument(
        "--gbif-csv",
        type=str,
        default=None,
        help="Optional path to exported CSV from GBIF Sequence-ID web tool",
    )
    parser.add_argument(
        "--max-sequences",
        type=int,
        default=None,
        help="Maximum number of sequences to process (for testing)",
    )
    parser.add_argument(
        "--skip-ncbi", action="store_true", help="Skip remote NCBI QBLAST to speed up execution"
    )
    parser.add_argument("--skip-bold", action="store_true", help="Skip BOLD Systems v5 querying")
    parser.add_argument(
        "--ncbi-delay",
        type=float,
        default=3.0,
        help="Delay in seconds between remote NCBI BLAST queries",
    )

    args = parser.parse_args()

    input_fasta = Path(args.input_fasta)
    output_xlsx = Path(args.output_xlsx)
    cache_dir = Path(args.cache_dir)

    if not input_fasta.exists():
        print(f"[Error] Input FASTA file not found: {input_fasta}")
        sys.exit(1)

    # Initialize cache manager
    cache_mgr = CacheManager(cache_dir)

    # Load sequences
    print(f"Reading FASTA: {input_fasta}")
    records = list(SeqIO.parse(input_fasta, "fasta"))
    if args.max_sequences:
        records = records[: args.max_sequences]
    print(f"Loaded {len(records)} sequence(s) to process.")

    seq_tuples = [(r.description, str(r.seq)) for r in records]

    # Source 1: Header Suffix Parsing
    parsed_meta = [parse_header_suffix(r.description) for r in records]

    # Source 2: BOLD Systems v5 ID Engine
    bold_results = {}
    if not args.skip_bold:
        bold_results = query_bold_v5_batch(seq_tuples, cache_mgr.bold_cache)
        cache_mgr.save()
    else:
        print("Skipping BOLD Systems v5 as requested.")

    # Source 3: NCBI BLAST
    ncbi_results = {}
    if not args.skip_ncbi:
        ncbi_results = query_ncbi_blast_batch(
            seq_tuples,
            cache_mgr.ncbi_cache,
            cache_mgr,
            batch_size=5,
            delay_between_batches=args.ncbi_delay,
        )
    else:
        print("Skipping NCBI BLAST as requested.")

    # Source 4: GBIF Backbone Matcher
    print("Matching taxonomy against GBIF Backbone...")
    gbif_results = {}
    for idx, r in enumerate(records):
        hdr = r.description
        meta = parsed_meta[idx]
        bold = bold_results.get(hdr, {})
        ncbi = ncbi_results.get(hdr, {})

        # Candidate name to check in GBIF (prioritize species then genus)
        candidate_name = (
            bold.get("top_species")
            or ncbi.get("top_species")
            or bold.get("top_genus")
            or ncbi.get("top_genus")
            or meta.get("field_inferred_genus")
            or ""
        )
        if candidate_name:
            gbif_match = query_gbif_species_match(candidate_name, cache_mgr.gbif_cache)
            gbif_results[hdr] = gbif_match
        else:
            gbif_results[hdr] = {}

    cache_mgr.save()

    # Synthesis & Concordance Evaluation
    combined_rows = []
    status_counts = {}

    for idx, r in enumerate(records):
        hdr = r.description
        meta = parsed_meta[idx]
        bold = bold_results.get(hdr, {})
        ncbi = ncbi_results.get(hdr, {})
        gbif = gbif_results.get(hdr, {})

        field_genus = meta.get("field_inferred_genus", "")
        bold_genus = bold.get("top_genus", "")
        ncbi_genus = ncbi.get("top_genus", "")
        gbif_genus = gbif.get("genus", "")

        bold_pident = bold.get("top_pct_identity", 0.0)
        ncbi_pident = ncbi.get("top_pct_identity", 0.0)

        consensus_genus, status, qc_flag = determine_concordance(
            field_genus, bold_genus, ncbi_genus, gbif_genus, bold_pident, ncbi_pident
        )

        status_counts[status] = status_counts.get(status, 0) + 1

        combined_rows.append(
            {
                "meta": meta,
                "bold": bold,
                "ncbi": ncbi,
                "gbif": gbif,
                "consensus_genus": consensus_genus,
                "concordance_status": status,
                "qc_flag": qc_flag,
            }
        )

    # Summary Output
    print("\n" + "=" * 60)
    print("Multi-Source Taxonomic Identification Summary:")
    print("=" * 60)
    for st, count in status_counts.items():
        print(f"  - {st}: {count} ({count / len(records) * 100:.1f}%)")
    print("=" * 60)

    # Export to Excel
    export_to_excel(combined_rows, output_xlsx)


if __name__ == "__main__":
    main()
