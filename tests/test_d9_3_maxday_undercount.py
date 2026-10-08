"""D9-3 (run 9): tool max/day undercounts on paid pages vs the rent-aware counter.

Offline, $0. Uses the committed CFk6 fixture so CI actually runs this guard.
If live-out/ti9 pages are present they are also checked (>25).
"""
import glob
import json
from pathlib import Path

W = Path(__file__).resolve().parents[1]
A = "CFk6sQA8hHUm1pvafGCr22oeCcbQZceft6Dt7hTGrYPy"
FIXTURE = W / "tests/fixtures/d9_3_cfk6"
LIVE = W / "live-out/ti9/raw/phase3" / A


def _records(directory):
    records = []
    for path in sorted(glob.glob(str(Path(directory) / "page*.bin"))):
        payload = json.loads(Path(path).read_bytes())
        records += [row for row in payload["result"]["data"] if isinstance(row, dict)]
    return records


def test_d9_3_tool_max_day_matches_hand_decoder():
    from scanner.mass_search import live_e2e as L
    from scanner.mass_search.canonical_records import canonical_decode_records

    expected = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))
    records = _records(FIXTURE)
    decoded = L.decode_supported_swaps(canonical_decode_records(records), A)
    rate = L.combined_economic_trade_rate(
        events=list(decoded.get("events") or []),
        records=records,
        address=A,
    )
    assert rate["max"] == expected["count"]
    assert rate["max_on"] == expected["day"]
    assert rate["max"] > 25

    if LIVE.exists():
        live_records = _records(LIVE)
        live_decoded = L.decode_supported_swaps(canonical_decode_records(live_records), A)
        live_rate = L.combined_economic_trade_rate(
            events=list(live_decoded.get("events") or []),
            records=live_records,
            address=A,
        )
        assert live_rate["max"] > 25
