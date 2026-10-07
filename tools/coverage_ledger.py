"""Exhaustive offline coverage ledger for the 2,000 research-search B records.

Window vs acquisition-support vs out-of-window, swap vs non-swap, decoded vs
unsupported, unresolved reason codes, and a discriminator histogram. Does not
call Helius or Birdeye.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/coverage"

INFRA = {
    "11111111111111111111111111111111",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    "ComputeBudget111111111111111111111111111111",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
    "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo",
}
WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
RANKS = {
    "gtfoTELAeEZHUgHetA6umfsCETiBMzJCN4tB2sqCgFL": 2,
    "CccSh2xwBvmiwiUwZRjQvktwTQHz8yypSPCKM3tHy1eU": 4,
    "BVZtNYBjivojQnJhocggTVqkbFDYNr2R61c6BZLkY9n9": 10,
    "BSN5bh8At4BkTGMoysA76fvsvoTsVpjaXRatNJYJBtCM": 11,
    "DQ7nsa6RPG9F6QjqDUa7LEN5CEvs9sPssXyRYVRb9Cys": 14,
    "A6PSQFRfv93hoAn1LhQGRT2dYQtjDKX6SE2vN9MEvbot": 15,
    "An9sREpLnAXVi4KMaTGuGvgET51CyaukLUTMtxzmLYSB": 17,
    "58PWvekDbHVPFB9FXGQrpumHD16NRajahkYLHiTvxvDL": 53,
    "AW6Pddy72jXDbMUPoSaTB7joJVvMmEMXaYPJhpRqMzD6": 56,
    "CRXomDFunLoRm5N54TyxCxAzn6NJtvnjKvuxudHSV68U": 90,
}


def _unix(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str) and value:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    return None


def _display(value):
    if value in (None, ""):
        return None
    quantized = Decimal(str(value)).quantize(Decimal("0.000000001"))
    text = format(quantized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def build_ledger():
    from scanner.investigation import (
        _accounts,
        _data,
        _keys,
        _program,
        decode_supported_swaps,
    )
    from scanner.mass_search.capture_catalog import (
        WINDOWS,
        catalog_by_address,
        load_capture_records,
    )
    from scanner.mass_search.canonical_records import canonical_decode_records, unwrap_gta_record
    from scanner.mass_search.record_breakdown import partition_records

    start = _unix(WINDOWS["report_start_inclusive"])
    end = _unix(WINDOWS["report_end_exclusive"])
    acquisition = _unix(WINDOWS["acquisition_support_start_inclusive"])
    catalog = catalog_by_address()
    records_out = []
    histogram = Counter()
    wallet_summaries = []
    for address, rank in RANKS.items():
        entry = catalog[address]
        raw_records, _ = load_capture_records(entry)
        wrapped = canonical_decode_records(raw_records)
        decoded = decode_supported_swaps(wrapped, address)
        breakdown = partition_records(
            wrapped,
            decoded,
            address,
            window_start=WINDOWS["report_start_inclusive"],
            window_end=WINDOWS["report_end_exclusive"],
            acquisition_start=WINDOWS["acquisition_support_start_inclusive"],
        )
        by_sig = {row["signature"]: row for row in breakdown["rows"]}
        unresolved_by_sig = defaultdict(list)
        for issue in decoded.get("unresolved") or []:
            unresolved_by_sig[issue.get("signature")].append(issue.get("reason") or "unspecified")
        decoded_by_sig = defaultdict(list)
        for event in decoded.get("events") or []:
            if event.get("kind") in ("buy", "sell", "conversion"):
                decoded_by_sig[event.get("signature")].append(event)
        for item in wrapped:
            raw = unwrap_gta_record(item)
            signature = item.get("signature")
            meta = raw.get("meta") if isinstance(raw, dict) else {}
            message = ((raw.get("transaction") or {}).get("message") if isinstance(raw, dict) else {}) or {}
            timestamp = raw.get("blockTime") if isinstance(raw, dict) else None
            version = raw.get("version", "legacy") if isinstance(raw, dict) else "legacy"
            if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
                if timestamp >= end:
                    window = "after_report_end"
                elif start is not None and timestamp >= start:
                    window = "in_report_window"
                elif acquisition is not None and timestamp >= acquisition:
                    window = "acquisition_support"
                else:
                    window = "before_acquisition_support"
            else:
                window = "timestamp_missing"
            try:
                keys = _keys(message, meta)
            except Exception:
                keys = []
            programs = []
            discs = []
            for instruction in message.get("instructions") or []:
                if not isinstance(instruction, dict):
                    continue
                try:
                    program = _program(instruction, keys)
                except Exception:
                    continue
                if not program or program in INFRA:
                    continue
                programs.append(program)
                try:
                    payload = _data(instruction.get("data") or "")
                    disc = payload[:8].hex() if payload else ""
                except Exception:
                    disc = ""
                discs.append({"program": program, "discriminator": disc})
                histogram[(program, disc)] += 1
            klass = (by_sig.get(signature) or {}).get("class")
            events = decoded_by_sig.get(signature) or []
            reasons = list(dict.fromkeys(unresolved_by_sig.get(signature) or []))
            assets = sorted({event.get("mint") for event in events if event.get("mint")})
            decoded_ok = bool(events)
            cash_resolved = decoded_ok and not any(
                "unresolved" in (reason or "").lower() or "uncertain" in (reason or "").lower()
                or "outside native" in (reason or "").lower()
                for reason in reasons
            )
            records_out.append({
                "address": address,
                "provider_rank": rank,
                "signature": signature,
                "version": version,
                "window_relation": window,
                "failed": bool((meta or {}).get("err")),
                "class": klass,
                "swap_candidate": klass in ("decoded_trade", "decoded_conversion", "unsupported_swap"),
                "decoded": decoded_ok,
                "decode_kinds": [event.get("kind") for event in events],
                "cash_inventory_capital_resolved": cash_resolved,
                "unresolved_reason_codes": reasons,
                "outer_programs": programs,
                "discriminators": discs,
                "affected_assets": assets,
                "venues": [
                    {"program": event.get("venue"), "instruction": event.get("instruction")}
                    for event in events
                ],
            })
        counts = breakdown["counts"]
        swap_den = counts["decoded_trade"] + counts["decoded_conversion"] + counts["unsupported_swap"]
        unresolved_share = None
        if swap_den:
            unresolved_share = _display(Decimal(counts["unsupported_swap"]) / Decimal(swap_den))
        unresolved_basis = _unresolved_basis_sales(address, decoded)
        wallet_summaries.append({
            "address": address,
            "provider_rank": rank,
            "transactions": 200,
            "counts": counts,
            "in_window_span": breakdown.get("in_window_span"),
            "unsupported_swap_share_in_window": breakdown.get("unsupported_swap_share_in_window"),
            "unresolved_swap_share": unresolved_share,
            "unresolved_basis_sales": unresolved_basis,
            "coverage_policy": _policy(
                unresolved_share,
                breakdown.get("unsupported_swap_share_in_window") or {},
                unresolved_basis,
            ),
            "unsupported_swaps_by_program": breakdown.get("unsupported_swaps_by_program") or {},
        })
    hist_rows = [
        {
            "program": program,
            "discriminator": disc,
            "count": count,
        }
        for (program, disc), count in histogram.most_common()
    ]
    payload = {
        "kind": "research-search-b-coverage-ledger-v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "windows": WINDOWS,
        "record_count": len(records_out),
        "unique_signatures": len({row["signature"] for row in records_out if row["signature"]}),
        "policy": {
            "provisional_shortlist": ">=99% resolved by count AND measurable notional, no unresolved dependency affecting qualifying positions",
            "watchlist": "95-99% with dependencies understood; incomplete evidence, not qualified",
            "blocked": "<95%, unknown denominator, material unknown notional, or unresolved dependency that can change the decision",
            "dependency_rule": "A missing purchase that could be the FIFO basis of a qualifying sale blocks regardless of percentage.",
        },
        "wallets": wallet_summaries,
        "discriminator_histogram": hist_rows,
        "records": records_out,
        "PRODUCT_READY": False,
    }
    return payload


def _unresolved_basis_sales(address, decoded):
    """Unresolved-sale count from decoded events plus opening inventory."""
    from scanner.mass_search.capture_catalog import WINDOWS
    from scanner.mass_search.g3_history import decoder_events_by_mint
    from scanner.mass_search.settlement import isolate_known_cost_events

    by_mint, _ = decoder_events_by_mint(
        decoded,
        address=address,
        window_start=WINDOWS["report_start_inclusive"],
        window_end=WINDOWS["report_end_exclusive"],
        acquisition_start=WINDOWS["acquisition_support_start_inclusive"],
    )
    rows = []
    for mint_rows in by_mint.values():
        rows.extend(mint_rows)
    _known, unresolved = isolate_known_cost_events(rows)
    return sum(1 for row in unresolved if row.get("kind") == "sell" and row.get("unresolved_basis"))


def _policy(unresolved_share, shares, unresolved_basis_sales=0):
    values = []
    if unresolved_share not in (None, ""):
        values.append(Decimal(str(unresolved_share)))
    for share in (shares.get("by_consideration") or {}).values():
        values.append(Decimal(str(share)))
    if not values:
        return "blocked_unknown_denominator"
    worst = max(values)
    resolved = Decimal("1") - worst
    dependency = int(unresolved_basis_sales or 0) > 0
    if resolved >= Decimal("0.99") and not dependency:
        return "provisional_eligible"
    if resolved >= Decimal("0.99") and dependency:
        return "coverage_eligibility_pending_reassessment"
    if resolved >= Decimal("0.95"):
        return "watchlist_incomplete_evidence"
    return "coverage_blocked"


def write_ledger(payload):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "LEDGER.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Research-search B coverage ledger",
        "",
        f"Generated {payload['generated_at']}. {payload['record_count']} records / {payload['unique_signatures']} unique signatures.",
        "",
        "PRODUCT_READY remains false. This ledger is offline over committed genuine pages only.",
        "",
        "## Coverage policy (item 12)",
        "",
        f"- Provisional shortlist: {payload['policy']['provisional_shortlist']}",
        f"- Watchlist: {payload['policy']['watchlist']}",
        f"- Blocked: {payload['policy']['blocked']}",
        f"- Dependency: {payload['policy']['dependency_rule']}",
        "",
        "## Per-wallet",
        "",
        "| Rank | Wallet | outside | failed | non_swap | unsupported_swap | decoded_trade | decoded_conversion | unresolved swap share | value share | policy | span h |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["wallets"]:
        counts = row["counts"]
        share = row.get("unsupported_swap_share_in_window") or {}
        value = ", ".join(f"{asset} {val}" for asset, val in (share.get("by_consideration") or {}).items()) or "—"
        lines.append(
            "| {rank} | {wallet} | {outside} | {failed} | {non_swap} | {unsupported} | {decoded} | {conv} | {ushare} | {value} | {policy} | {span} |".format(
                rank=row["provider_rank"],
                wallet=row["address"][:4] + "…" + row["address"][-4:],
                outside=counts.get("outside_window", 0),
                failed=counts.get("failed", 0),
                non_swap=counts.get("non_swap", 0),
                unsupported=counts.get("unsupported_swap", 0),
                decoded=counts.get("decoded_trade", 0),
                conv=counts.get("decoded_conversion", 0),
                ushare=row.get("unresolved_swap_share") or "—",
                value=value,
                policy=row.get("coverage_policy"),
                span=((row.get("in_window_span") or {}).get("hours") or "—"),
            )
        )
    lines.extend(["", "## Discriminator histogram (outer non-infra, all 2,000 records)", "", "| Count | Program | Discriminator |", "| --- | --- | --- |"])
    for row in payload["discriminator_histogram"][:40]:
        lines.append(f"| {row['count']} | `{row['program']}` | `{row['discriminator']}` |")
    lines.extend([
        "",
        "## Notes",
        "",
        "- Non-swaps are excluded from the swap denominator and stay on the inventory ledger.",
        "- Out-of-window records are kept because earlier txs can affect opening basis.",
        "- Item 12 policy uses both swap-coverage shares and unresolved-basis dependencies.",
        "- coverage_status and qualification_level are different fields from one source of truth (`scanner.mass_search.labels`). An9s is coverage_status=provisional_eligible and qualification_level=conditional_captured_lot_result (1 completed episode < min_sample 3; 27 open lots). CccS is coverage_status=coverage_eligibility_pending_reassessment (sensitivity sign-flip) and qualification_level=conditional_captured_lot_result, never a provisional_research_lead. gtfo and A6PS stay coverage_eligibility_pending_reassessment on unresolved-basis sales.",
        "- L2TExMFK…, OKX, and DFlow stay unsupported unless a later review can name the interface with confidence.",
        "",
    ])
    (OUT / "LEDGER.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "HISTOGRAM.json").write_text(
        json.dumps({"kind": "research-search-b-discriminator-histogram-v1", "rows": payload["discriminator_histogram"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    return OUT


def main():
    payload = build_ledger()
    path = write_ledger(payload)
    print(f"wrote {payload['record_count']} records to {path}")


if __name__ == "__main__":
    main()
