"""Address → cached capture registry. Genuine and labelled synthetic stay distinct."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from scanner.investigation import DECODER_VERSION
from scanner.mass_search.canonical_records import gta_records_from_capture
from scanner.mass_search.g3_reacquire import ALLOWED_WALLET

ROOT = Path(__file__).resolve().parents[2]
GENUINE_RANK1_PATH = ROOT / "evidence/mass-wallet-funnel/ranked100-anchored-validation-live/SOURCE_RESPONSE_page0.json"
EXPECTED_CAPTURE_SHA = "53a5c6f46ec2e0f8c895df6398116756ae3728892f0a6b702137f56d8624328d"
RANKED_SNAPSHOT_ID = "ranked100-discovery-pilot-2026-10-05"
ANALYSIS_VERSION = (
    "analysis-v6-research-screen-v2+sol-isolate-v1+mixed-quote-v1+"
    "sig-keyed-v1+quote-conversion-v1+fees-tips-v1+coverage-v1+mitch-review-v1+"
    "chatgpt-review-2026-10-07-v1+rereview-0346-v1+rereview-0547-v1+rereview-0714-v1+rereview-0842-v1+rereview-2fe60bd-v1+"
    "result-relevant-coverage-v1"
)
RESEARCH_SEARCH_DIR = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06"
RESEARCH_SEARCH_MANIFEST = RESEARCH_SEARCH_DIR / "CAPTURE_MANIFEST.json"
RESEARCH_SEARCH_AUTHORIZATION_ID = "live-ranked100-research-search-2026-10-06-mitch"
G1_ARCHIVE = ROOT / (
    "evidence/mass-wallet-funnel/1bffe2ac21854424aa3fe3b8bf6a22ae/"
    "archives/helius_gta_survivor_desc100.json.gz"
)
G1_ADDRESS = "GatgyE2SqnNNjNeNGR8MG1VSVxFGxgyjB111hYJRTkee"
G1_MINT = "4oPr8EG6qxbYksWt2F3rJ4CqqvpcPrZ4aWg4ByDJpump"
G1_PNL = "-0.167725526"
G1_HOLD_SECONDS = 598
FIXTURE_DIR = ROOT / "tests/fixtures/synthetic_engineering"
WINDOWS = {
    "report_start_inclusive": "2026-09-05T13:29:27Z",
    "report_end_exclusive": "2026-10-05T13:29:27Z",
    "acquisition_support_start_inclusive": "2026-07-07T13:29:27Z",
}
G1_WINDOWS = {
    "report_start_inclusive": "2026-09-05T12:11:35.382917Z",
    "report_end_exclusive": "2026-10-05T12:11:35.382917Z",
    "acquisition_support_start_inclusive": "2026-06-07T12:11:35.382917Z",
}


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _synthetic_entries():
    entries = []
    if not FIXTURE_DIR.exists():
        return entries
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        payload = _load_json(path)
        if payload.get("kind") != "SYNTHETIC_ENGINEERING_FIXTURE":
            continue
        entries.append({
            "address": payload["address"],
            "mode": "synthetic_events",
            "path": str(path),
            "sha256": _sha256(path),
            "corpus_kind": "SYNTHETIC",
            "label": payload.get("label") or "SYNTHETIC — engineering fixture, not proof",
            "not_proof": True,
            "raise_on_replay": bool(payload.get("raise_on_replay")),
            "error": payload.get("error"),
            "events": payload.get("events") or [],
            "windows": {
                "report_start_inclusive": payload.get("window_start") or WINDOWS["report_start_inclusive"],
                "report_end_exclusive": payload.get("window_end") or WINDOWS["report_end_exclusive"],
                "acquisition_support_start_inclusive": WINDOWS["acquisition_support_start_inclusive"],
            },
            "decoder_version": DECODER_VERSION,
            "evidence_status": "synthetic_engineering_fixture",
        })
    return entries


def _research_search_entries():
    if not RESEARCH_SEARCH_MANIFEST.exists():
        return []
    manifest = json.loads(RESEARCH_SEARCH_MANIFEST.read_text(encoding="utf-8"))
    grouped = {}
    for page in (manifest.get("pages") or {}).values():
        grouped.setdefault(page["address"], []).append(page)
    entries = []
    for address, pages in grouped.items():
        pages = sorted(pages, key=lambda item: item.get("page_index") or 0)
        page_specs = []
        for page in pages:
            path = RESEARCH_SEARCH_DIR / page["repo_gz_path"]
            page_specs.append({
                "address": address,
                "page_index": page["page_index"],
                "path": str(path),
                "raw_sha256": page["raw_sha256"],
                "gz_sha256": page.get("gz_sha256"),
                "raw_bytes": page.get("raw_bytes"),
                "record_count": page.get("record_count"),
            })
        first = page_specs[0]
        entries.append({
            "address": address,
            "mode": "genuine_gta",
            "path": first["path"],
            "sha256": first["raw_sha256"],
            "pages": page_specs,
            "multi_page": True,
            "corpus_kind": "GENUINE_REPLAY",
            "label": "Genuine ranked-100 research-search capture (2 newest-first GTA pages)",
            "not_proof": False,
            "raise_on_replay": False,
            "windows": dict(WINDOWS),
            "decoder_version": DECODER_VERSION,
            "evidence_status": "cached_capture",
            "authorization_id": RESEARCH_SEARCH_AUTHORIZATION_ID,
            "source_id": "ranked100-research-search-b-replay",
            "provider_rank": pages[0].get("provider_rank"),
        })
    return entries


def catalog_entries():
    genuine = {
        "address": ALLOWED_WALLET,
        "mode": "genuine_gta",
        "path": str(GENUINE_RANK1_PATH),
        "sha256": EXPECTED_CAPTURE_SHA,
        "corpus_kind": "GENUINE_REPLAY",
        "label": "Genuine ranked-100 rank-1 page-0 capture",
        "not_proof": False,
        "raise_on_replay": False,
        "windows": dict(WINDOWS),
        "decoder_version": DECODER_VERSION,
        "evidence_status": "cached_capture",
        "authorization_id": "live-ranked100-anchored-validation-2026-10-06-mitch",
        "source_id": "ranked100-product-completion-offline-replay",
    }
    control = {
        "address": G1_ADDRESS,
        "mode": "genuine_gta",
        "path": str(G1_ARCHIVE),
        "sha256": _sha256(G1_ARCHIVE) if G1_ARCHIVE.exists() else None,
        "corpus_kind": "GENUINE_REPLAY",
        "label": "Genuine G1 SOL control archive — not a ranked-100 candidate proof",
        "not_proof": False,
        "raise_on_replay": False,
        "windows": dict(G1_WINDOWS),
        "decoder_version": DECODER_VERSION,
        "evidence_status": "cached_control_archive",
        "authorization_id": "offline-g1-archive-replay",
        "source_id": "g1-product-control-offline-replay",
        "control": True,
        "mint": G1_MINT,
    }
    return [genuine, control, *_research_search_entries(), *_synthetic_entries()]


def catalog_by_address():
    return {entry["address"]: entry for entry in catalog_entries()}


def genuine_captured_addresses():
    return {
        entry["address"]
        for entry in catalog_entries()
        if entry.get("mode") == "genuine_gta" and not entry.get("control")
    }


def _load_page_bytes(path):
    path = Path(path)
    file_bytes = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(file_bytes)
    else:
        raw = file_bytes
    return raw, file_bytes


def load_capture_records(entry):
    pages = entry.get("pages")
    if pages:
        records = []
        raw_digests = []
        seen = set()
        for page in sorted(pages, key=lambda item: item.get("page_index") or 0):
            raw, _file_bytes = _load_page_bytes(page["path"])
            raw_sha = hashlib.sha256(raw).hexdigest()
            expected = page.get("raw_sha256")
            if expected and raw_sha != expected:
                raise ValueError("Cached capture hash drifted")
            payload = json.loads(raw)
            page_records = gta_records_from_capture(payload)
            for record in page_records:
                signature = None
                tx = record.get("transaction") if isinstance(record, dict) else None
                if isinstance(tx, dict):
                    sigs = tx.get("signatures")
                    if isinstance(sigs, list) and sigs:
                        signature = sigs[0]
                if signature and signature in seen:
                    continue
                if signature:
                    seen.add(signature)
                records.append(record)
            raw_digests.append(raw_sha)
        digest = hashlib.sha256("".join(raw_digests).encode("utf-8")).hexdigest()
        return records, digest
    path = Path(entry["path"])
    raw, file_bytes = _load_page_bytes(path)
    if entry.get("sha256") and entry["sha256"] == hashlib.sha256(raw).hexdigest():
        digest = entry["sha256"]
    else:
        digest = hashlib.sha256(file_bytes).hexdigest()
        expected = entry.get("sha256")
        if expected and digest != expected and expected != hashlib.sha256(raw).hexdigest():
            raise ValueError("Cached capture hash drifted")
        if expected == hashlib.sha256(raw).hexdigest():
            digest = expected
    payload = json.loads(raw)
    records = gta_records_from_capture(payload)
    return records, digest


def ranked_snapshot_identity():
    raw = ROOT / "evidence/mass-wallet-funnel/ranked100-discovery-pilot-2026-10-05/RAW.json"
    short = ROOT / "evidence/mass-wallet-funnel/ranked100-discovery-pilot-2026-10-05/SHORTLIST.json"
    return {
        "snapshot_id": RANKED_SNAPSHOT_ID,
        "raw_sha256": _sha256(raw) if raw.exists() else None,
        "shortlist_sha256": _sha256(short) if short.exists() else None,
    }


def evidence_cache_key(entry, *, extra=None):
    snapshot = ranked_snapshot_identity()
    material = "|".join([
        entry["address"],
        str(entry.get("sha256") or ""),
        str(entry.get("decoder_version") or DECODER_VERSION),
        str((entry.get("windows") or {}).get("report_start_inclusive") or ""),
        str((entry.get("windows") or {}).get("report_end_exclusive") or ""),
        str(entry.get("mint") or ""),
        ANALYSIS_VERSION,
        str(snapshot.get("raw_sha256") or ""),
        str(extra or ""),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
