"""D9-3 (run 9): tool max/day undercounts on paid pages vs a stdlib hand decoder.
Offline, $0: reads the persisted run-9 pages for CFk6sQA8 (ti9). Hand: 145 econ trades on 2026-09-30."""
import glob, json, subprocess, sys
from pathlib import Path
import pytest
W = Path(__file__).resolve().parents[1]
A = "CFk6sQA8hHUm1pvafGCr22oeCcbQZceft6Dt7hTGrYPy"
PD = W / "live-out/ti9/raw/phase3" / A


@pytest.mark.skipif(not PD.exists(), reason="run-9 pages not present")
def test_d9_3_tool_max_day_matches_hand_decoder():
    from scanner.mass_search import live_e2e as L
    from scanner.mass_search.canonical_records import canonical_decode_records
    records = []
    for p in sorted(glob.glob(str(PD / "page*.bin"))):
        records += [t for t in json.loads(open(p, "rb").read())["result"]["data"] if isinstance(t, dict)]
    decoded = L.decode_supported_swaps(canonical_decode_records(records), A)
    rate = L.combined_economic_trade_rate(events=list(decoded.get("events") or []), records=records, address=A)
    out = subprocess.run([sys.executable, str(W / "probes/day_hand.py"), A, str(PD), "2026-09-30"],
                         capture_output=True, text=True, check=True).stdout.splitlines()[1]
    hand = int(out.split(":")[1].split()[0])
    assert hand > 25
    assert rate["max"] > 25, ("tool", rate.get("max"), rate.get("max_on"), "hand 2026-09-30", hand)
