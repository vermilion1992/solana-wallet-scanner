#!/usr/bin/env python3
"""Compare the decoder-independent auditor to app episodes. Uses scanner for the app side only."""
from __future__ import annotations

import json
import tempfile
from decimal import Decimal
from pathlib import Path

from scanner.mass_search.capture_catalog import catalog_by_address
from scanner.mass_search.workflow import replay_captured_wallet
from scanner.storage import Store
from tools.independent_episode_audit import JUPITER, METEORA_DAMM_V2, PINNED, PUMP, PUMP_SWAP, RFQ_FILL, audit_address

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/coverage/INDEPENDENT_AUDIT.json"
MANIFEST = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/CAPTURE_MANIFEST.json"
AUDITED_PROGRAMS = {program for program, _disc in PINNED}

LABELLED = {
    "gtfoTELAeEZHUgHetA6umfsCETiBMzJCN4tB2sqCgFL",
    "CccSh2xwBvmiwiUwZRjQvktwTQHz8yypSPCKM3tHy1eU",
    "A6PSQFRfv93hoAn1LhQGRT2dYQtjDKX6SE2vN9MEvbot",
    "An9sREpLnAXVi4KMaTGuGvgET51CyaukLUTMtxzmLYSB",
    "58PWvekDbHVPFB9FXGQrpumHD16NRajahkYLHiTvxvDL",
}


def _q(value):
    if value in (None, ""):
        return None
    return Decimal(str(value)).quantize(Decimal("0.000000001"))


# Two lamports. 1e-8 SOL is 10 lamports and is too wide for a 9-decimal SOL
# quantity. Quantized nets can differ by 1–2 lamports after isolate-then-FIFO.
TWO_LAMPORTS_SOL = Decimal("0.000000002")


def _nets_match(left, right):
    a, b = _q(left), _q(right)
    if a is None or b is None:
        return False
    return abs(a - b) <= TWO_LAMPORTS_SOL


def _venue_label(program, instructions):
    names = [name for name in (instructions or []) if name]
    if program == RFQ_FILL:
        return "RFQ_Fill"
    if program == JUPITER:
        return "Jupiter " + " / ".join(names) if names else "Jupiter"
    if program == PUMP_SWAP:
        return "PumpSwap " + " / ".join(names) if names else "PumpSwap"
    if program == PUMP:
        return "Pump " + " / ".join(names) if names else "Pump"
    if program == METEORA_DAMM_V2:
        return "Meteora DAMM v2 " + " / ".join(names) if names else "Meteora DAMM v2"
    return " / ".join(names) if names else program


def _venue_notes_from_auditor(independent):
    """Compute venue notes from the auditor's own reconstructed mints.

    Not handwritten. A mint that reconstructs but does not FIFO-close is
    labelled reconstructed_as_trades, not a clean completed episode.
    """
    notes = {}
    for row in independent.get("reconstructed_mints") or []:
        mint = row.get("mint") or ""
        if not mint:
            continue
        programs = list(row.get("programs") or [])
        instructions = list(row.get("instructions") or [])
        assets = list(row.get("settlement_assets") or [])
        program = programs[0] if len(programs) == 1 else programs
        note = {
            "mint": mint,
            "program": program,
            "venue": _venue_label(programs[0], instructions) if len(programs) == 1 else [
                _venue_label(item, instructions) for item in programs
            ],
            "settlement": assets[0] if len(assets) == 1 else assets,
            "reconstructed": True,
            "computed_from_auditor_decode": True,
        }
        if not row.get("clean_completed_episode"):
            note["reconstructed_as_trades"] = True
            note["clean_completed_episode"] = False
            note["reason"] = (
                "Independently reconstructed; FIFO leaves opening inventory / leftover "
                "so this mint is not a clean completed episode."
            )
        notes[f"{mint}_sales"] = note
    return notes or None


def _sale_proceeds(row):
    if row.get("proceeds") not in (None, ""):
        return Decimal(str(row["proceeds"]))
    basis = Decimal(str(row.get("basis") or 0))
    gross = Decimal(str(row.get("gross_profit") or 0))
    return basis + gross


def _event_units(row):
    for key in ("units", "quantity_raw", "quantity"):
        if row.get(key) not in (None, ""):
            return Decimal(str(row[key]))
    return Decimal("0")


def _event_order(row):
    if isinstance(row.get("order"), int) and not isinstance(row.get("order"), bool):
        return (row["order"], row.get("signature") or "")
    return (
        row.get("slot") if isinstance(row.get("slot"), int) else 0,
        row.get("transaction_index") if isinstance(row.get("transaction_index"), int) else (
            row.get("transactionIndex") if isinstance(row.get("transactionIndex"), int) else 0
        ),
        row.get("timestamp") or row.get("blockTime") or 0,
        row.get("signature") or "",
    )


def _app_episodes(report):
    events = [row for row in (report.get("events") or []) if row.get("kind") in ("buy", "sell")]
    worksheet = report.get("worksheet") or {}
    sales = []
    seen = set()
    sources = [worksheet]
    sources.extend((worksheet.get("by_quote_asset") or {}).values())
    for part in sources:
        if not part:
            continue
        for row in part.get("sale_rows") or []:
            key = (row.get("signature"), row.get("split_part") or "matched", row.get("mint"))
            if key in seen:
                continue
            seen.add(key)
            sales.append(row)
    clean_sales = []
    for row in sales:
        if row.get("unresolved_basis") or row.get("not_clean_episode") or row.get("split_part") == "unresolved":
            continue
        clean_sales.append(row)
    sales_by_sig = {}
    for row in clean_sales:
        sales_by_sig.setdefault(row.get("signature"), []).append(row)
    by_mint = {}
    for event in events:
        mint = event.get("mint")
        if not mint:
            continue
        by_mint.setdefault(mint, []).append(event)
    episodes = []
    for mint, rows in by_mint.items():
        rows = sorted(rows, key=_event_order)
        inventory = Decimal("0")
        opened = False
        episode_sigs = []
        for event in rows:
            units = _event_units(event)
            if event.get("kind") == "buy":
                inventory += units
                opened = True
                continue
            if event.get("kind") != "sell":
                continue
            if not opened or inventory <= 0:
                continue
            inventory -= units
            episode_sigs.append(event.get("signature"))
            if inventory < 0:
                opened = False
                episode_sigs = []
                inventory = Decimal("0")
                continue
            if inventory != 0:
                continue
            mint_sales = []
            for signature in episode_sigs:
                mint_sales.extend(sales_by_sig.get(signature) or [])
            close = event
            venue = close.get("venue") or close.get("source") or close.get("program")
            if mint_sales:
                net = sum(Decimal(str(row.get("net_profit") or 0)) for row in mint_sales)
                basis = sum(Decimal(str(row.get("basis") or 0)) for row in mint_sales)
                proceeds = sum(_sale_proceeds(row) for row in mint_sales)
                fees = sum(Decimal(str(row.get("fees_and_tips") or 0)) for row in mint_sales)
            else:
                net = basis = proceeds = fees = None
            episodes.append({
                "mint": mint,
                "close_signature": close.get("signature"),
                "venue": venue,
                "instruction": close.get("instruction"),
                "basis": str(basis) if basis is not None else None,
                "proceeds": str(proceeds) if proceeds is not None else None,
                "verified_costs": str(fees) if fees is not None else None,
                "net": str(net) if net is not None else None,
                "auditor_covers_venue": venue in AUDITED_PROGRAMS if venue else False,
            })
            opened = False
            episode_sigs = []
    if episodes:
        return episodes
    # Fallback: one row per mint that the worksheet already treated as completed.
    detail = (report.get("completed_episode_detail") or {}).get("per_mint_detail") or {}
    for mint, counted in detail.items():
        if int((counted or {}).get("completed_episodes") or 0) < 1:
            continue
        mint_sales = [row for row in clean_sales if row.get("mint") == mint]
        mint_events = [row for row in events if row.get("mint") == mint]
        close = None
        for row in reversed(mint_events):
            if row.get("kind") == "sell":
                close = row
                break
        if not mint_sales and not close:
            continue
        last = mint_sales[-1] if mint_sales else {}
        venue = (close or {}).get("venue") or (close or {}).get("source") or (close or {}).get("program")
        net = sum(Decimal(str(row.get("net_profit") or 0)) for row in mint_sales)
        basis = sum(Decimal(str(row.get("basis") or 0)) for row in mint_sales)
        proceeds = sum(_sale_proceeds(row) for row in mint_sales)
        fees = sum(Decimal(str(row.get("fees_and_tips") or 0)) for row in mint_sales)
        episodes.append({
            "mint": mint,
            "close_signature": (close or last).get("signature"),
            "venue": venue,
            "instruction": (close or {}).get("instruction"),
            "basis": str(basis) if mint_sales else last.get("basis"),
            "proceeds": str(proceeds) if mint_sales else last.get("proceeds"),
            "verified_costs": str(fees) if mint_sales else last.get("fees_and_tips"),
            "net": str(net) if mint_sales else last.get("net_profit"),
            "auditor_covers_venue": venue in AUDITED_PROGRAMS if venue else False,
        })
    return episodes


def compare_wallet(address, pages, tmp):
    store = Store(tmp / address)
    result = replay_captured_wallet(store, address, force=True)
    report = result["report"] or {}
    store.close()
    app = _app_episodes(report)
    independent = audit_address(address, pages)
    indep_by_sig = {row.get("close_signature"): row for row in independent.get("episodes") or []}
    indep_by_mint = {row.get("mint"): row for row in independent.get("episodes") or []}
    rows = []
    unaudited_venues = []
    for episode in app:
        venue = episode.get("venue")
        if venue and venue not in AUDITED_PROGRAMS:
            unaudited_venues.append(venue)
        match = indep_by_sig.get(episode.get("close_signature")) or indep_by_mint.get(episode.get("mint"))
        venue = episode.get("venue") or (match or {}).get("venue")
        rows.append({
            "mint": episode.get("mint"),
            "close_signature": episode.get("close_signature"),
            "venue": venue,
            "auditor_covers_venue": bool(venue in AUDITED_PROGRAMS) if venue else bool(match),
            "app": {
                "basis": episode.get("basis"),
                "proceeds": episode.get("proceeds"),
                "verified_costs": episode.get("verified_costs"),
                "net": episode.get("net"),
            },
            "auditor": None if not match else {
                "basis": match.get("basis_sol"),
                "proceeds": match.get("proceeds_sol"),
                "verified_costs": match.get("verified_costs_sol"),
                "net": match.get("net_profit_sol"),
            },
            "match": bool(match) and _nets_match((match or {}).get("net_profit_sol"), episode.get("net")),
        })
    completed = int(report.get("wallet_completed_episodes") or 0)
    auditor_count = int(independent.get("clean_episodes") or 0)
    if not app and auditor_count:
        # App reconstructed 0 completed episodes; the auditor found some.
        # That is a mismatch, not an empty-wallet no_completed_episodes status.
        status = "not_independently_audited"
    elif not app:
        status = "not_independently_audited" if completed else "no_completed_episodes"
    elif completed and all(row.get("match") for row in rows) and len(rows) == completed and auditor_count == completed:
        status = "independently_audited"
    else:
        status = "not_independently_audited"
    notes = _venue_notes_from_auditor(independent)
    episode_net = independent.get("independently_audited_episode_net")
    episode_unit = independent.get("independently_audited_episode_net_unit")
    worksheet = report.get("worksheet") or {}
    by_quote = worksheet.get("by_quote_asset") or {}
    worksheet_total = None
    worksheet_unit = None
    if episode_unit == "USDC":
        usdc = by_quote.get("USDC") or {}
        worksheet_total = usdc.get("total_profit_usdc") or worksheet.get("total_profit_usdc")
        worksheet_unit = "USDC"
    elif episode_unit == "SOL":
        sol = by_quote.get("SOL") or {}
        worksheet_total = sol.get("total_profit_sol") or worksheet.get("total_profit_sol")
        worksheet_unit = "SOL"
    worksheet_matches_episodes = (
        worksheet_total not in (None, "")
        and episode_net not in (None, "")
        and _nets_match(worksheet_total, episode_net)
    )
    return {
        "address": address,
        "records": independent.get("records"),
        "independently_reconstructed_trades": independent.get("independently_reconstructed_trades"),
        "app_completed_episodes": report.get("wallet_completed_episodes"),
        "auditor_clean_episodes": independent.get("clean_episodes"),
        "status": status,
        "independently_audited": status == "independently_audited",
        "independently_audited_episode_net": episode_net if status == "independently_audited" and episode_unit != "mixed" else None,
        "independently_audited_episode_net_unit": episode_unit if status == "independently_audited" and episode_unit != "mixed" else None,
        "independently_audited_episode_nets_by_unit": independent.get("independently_audited_episode_nets_by_unit"),
        "worksheet_total": worksheet_total,
        "worksheet_total_unit": worksheet_unit,
        "worksheet_total_independently_audited": bool(worksheet_matches_episodes) if status == "independently_audited" else False,
        "unaudited_venues": sorted(set(unaudited_venues)),
        "episodes": rows,
        "auditor_only_episodes": independent.get("episodes") or [],
        "reconstructed_mints": independent.get("reconstructed_mints") or [],
        "venue_notes": notes,
        "imports_scanner_in_auditor": False,
        "source": "raw_instructions_balances_ownership_pinned_interfaces",
        "PRODUCT_READY": False,
    }


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_address = {}
    for entry in (manifest.get("pages") or {}).values():
        by_address.setdefault(entry["address"], []).append(entry)
    tmp = Path(tempfile.mkdtemp(prefix="episode-compare-"))
    wallets = []
    for address, pages in sorted(by_address.items()):
        pages = sorted(pages, key=lambda item: item.get("page_index") or 0)
        wallets.append(compare_wallet(address, pages, tmp))
    payload = {
        "kind": "independent-episode-audit-v1",
        "wallets": wallets,
        "labelled_wallets": sorted(LABELLED),
        "imports_scanner": False,
        "PRODUCT_READY": False,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "wallets": [
            {"address": row["address"], "status": row["status"], "app": row["app_completed_episodes"], "auditor": row["auditor_clean_episodes"]}
            for row in wallets
        ]
    }, indent=2))


if __name__ == "__main__":
    main()
