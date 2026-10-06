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
ANALYSIS_VERSION = "analysis-v3-partial-match-v1+material-exit-v2+usdc-fifo-v1"
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
    return [genuine, control, *_synthetic_entries()]


def catalog_by_address():
    return {entry["address"]: entry for entry in catalog_entries()}


def genuine_captured_addresses():
    return {
        entry["address"]
        for entry in catalog_entries()
        if entry.get("mode") == "genuine_gta" and not entry.get("control")
    }


def load_capture_records(entry):
    path = Path(entry["path"])
    if path.suffix == ".gz":
        payload = json.loads(gzip.open(path, "rb").read())
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    records = gta_records_from_capture(payload)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    expected = entry.get("sha256")
    if expected and digest != expected:
        raise ValueError("Cached capture hash drifted")
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
