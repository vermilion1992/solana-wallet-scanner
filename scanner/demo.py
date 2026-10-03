"""Synthetic controls. These are never presented as observed on-chain wallets."""
from datetime import datetime, timedelta, timezone
import uuid


def _base58(data):
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = int.from_bytes(data, "big")
    result = ""
    while number:
        number, digit = divmod(number, 58)
        result = alphabet[digit] + result
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + result


def create_demo_reports(store, preset):
    from .accounting import analyze, evaluate_policy, METHODOLOGY
    # The calibration fixture has a fixed 30/90-day population, independent of
    # the owner's next live collection settings.
    preset = {**preset, "window_days": 30, "verification_days": 90}
    end = datetime.now(timezone.utc).replace(microsecond=0, minute=0, second=0)
    start = end - timedelta(days=30)
    scan_id = uuid.uuid4().hex
    reports = []
    for sample, label in enumerate(("Patient accumulator", "Rapid rotation", "Unresolved allocation")):
        address = _base58(bytes([sample + 31]) * 32)
        events = []
        for index in range(110):
            # Seventy completions in the report window and forty earlier.
            close = start + timedelta(hours=12 + index * 10) if index < 70 else end - timedelta(days=31 + (index - 70), hours=12)
            opened = close - (timedelta(minutes=2) if sample == 1 else timedelta(hours=6))
            mint = _base58(bytes([101 + index % 20]) * 32)
            proceeds = "1.2" if index % 10 < 7 else "0.95"
            shared = {"mint": mint, "quantity_raw": "1000000000", "decimals": 6,
                      "classification": "meme", "paid_by_wallet": True, "fee_sol": "0.000005"}
            events.extend([
                {**shared, "kind": "buy", "timestamp": opened.isoformat(), "order": index * 2,
                 "amount_sol": "1", "signature": f"synthetic-{sample}-{index}-buy", "path": "synthetic/buy"},
                {**shared, "kind": "sell", "timestamp": close.isoformat(), "order": index * 2 + 1,
                 "amount_sol": proceeds, "signature": f"synthetic-{sample}-{index}-sell", "path": "synthetic/sell"},
            ])
        if sample == 2:
            events.append({"kind": "transfer_in", "timestamp": (end - timedelta(days=2)).isoformat(),
                           "order": 999, "mint": _base58(bytes([150]) * 32), "quantity_raw": "1000000", "decimals": 6,
                           "classification": "meme", "signature": "synthetic-unresolved-allocation", "path": "synthetic/transfer"})
            events.append({"kind": "sell", "timestamp": (end - timedelta(days=1)).isoformat(), "order": 1000,
                           "mint": _base58(bytes([150]) * 32), "quantity_raw": "1000000", "decimals": 6,
                           "amount_sol": "2", "fee_sol": "0.000005", "classification": "meme",
                           "signature": "synthetic-unresolved-sale", "path": "synthetic/sale"})
        digest = store.archive({"kind": "synthetic-control", "warning": "Generated offline fixture. Not blockchain evidence or a wallet recommendation.",
                                "label": label, "events": events})
        for event in events:
            event["evidence"] = [digest]
        # Closed synthetic system with independently specified boundaries.
        result = analyze(events, start.isoformat(), end.isoformat(), opening_equity="100", closing_equity="108.7493" if sample < 2 else None,
                         external_deposits="0", external_withdrawals="0")
        evaluated = evaluate_policy(result["metrics"], preset, evidence_verified=sample < 2)
        report = {"id": uuid.uuid4().hex, "scan_id": scan_id, "address": address, "label": label, "source": "demo",
                  "created_at": datetime.now(timezone.utc).isoformat(), "window": {"start": start.isoformat(), "end": end.isoformat()},
                  "methodology": METHODOLOGY, "preset": preset, "evidence_status": "verified" if sample < 2 else "partial",
                  **result, **evaluated, "events": events,
                  "coverage": {"scope": "Synthetic event population only", "history_scope_complete": sample < 2,
                               "transactions": len(events), "account_discovery": "Generated fixture; not on-chain ownership evidence",
                               "missing_records": [], "basis": "Known synthetic purchases" if sample < 2 else "One allocation has unknown cost basis"},
                  "evidence": [{"hash": digest, "kind": "synthetic-control"}],
                  "notes": ["OFFLINE DEMO: synthetic wallets, transactions, classifications and equity boundaries.",
                            "These controls exercise the accounting and screening engine; they do not establish live provider capability."]}
        store.put("reports", report["id"], report)
        reports.append(report)
    scan = {"id": scan_id, "source": "demo", "status": "completed", "stage": "Offline controls completed", "created_at": end.isoformat(),
            "window": {"start": start.isoformat(), "end": end.isoformat()}, "addresses": [r["address"] for r in reports],
            "progress": {"wallets_completed": 3, "wallets_total": 3, "pages": 0, "transactions": 0, "credits": 0, "unresolved": 1},
            "checkpoint": {}, "reason": "Synthetic data; no provider requests."}
    store.put("scans", scan_id, scan)
    return scan_id
