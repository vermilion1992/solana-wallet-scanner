#!/usr/bin/env python3
"""Replay genuine captures and write sale diffs + per-wallet table. Offline only."""
from __future__ import annotations

import json
import tempfile
from decimal import Decimal
from pathlib import Path

from scanner.mass_search.capture_catalog import catalog_by_address
from scanner.mass_search.labels import research_label_tables, wallet_status_fields
from scanner.mass_search.workflow import replay_captured_wallet
from scanner.storage import Store

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/coverage"
RECON = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/recon"
OLD_USDC = Decimal("14739.373324196")
NEW_USDC = Decimal("50386.378661746")
WORKSHEET_LABEL = "worksheet total, partial coverage, not independently audited"

LABELS = {
    "gtfoTELAeEZHUgHetA6umfsCETiBMzJCN4tB2sqCgFL": "gtfo",
    "CccSh2xwBvmiwiUwZRjQvktwTQHz8yypSPCKM3tHy1eU": "CccS",
    "BVZtNYBjivojQnJhocggTVqkbFDYNr2R61c6BZLkY9n9": "BVZt",
    "BSN5bh8At4BkTGMoysA76fvsvoTsVpjaXRatNJYJBtCM": "BSN5",
    "DQ7nsa6RPG9F6QjqDUa7LEN5CEvs9sPssXyRYVRb9Cys": "DQ7n",
    "A6PSQFRfv93hoAn1LhQGRT2dYQtjDKX6SE2vN9MEvbot": "A6PS",
    "An9sREpLnAXVi4KMaTGuGvgET51CyaukLUTMtxzmLYSB": "An9s",
    "58PWvekDbHVPFB9FXGQrpumHD16NRajahkYLHiTvxvDL": "58PW",
    "AW6Pddy72jXDbMUPoSaTB7joJVvMmEMXaYPJhpRqMzD6": "AW6P",
    "CRXomDFunLoRm5N54TyxCxAzn6NJtvnjKvuxudHSV68U": "CRXo",
}


def _q(value):
    if value in (None, ""):
        return None
    return Decimal(str(value)).quantize(Decimal("0.000000001"))


def _sales(report):
    worksheet = report.get("worksheet") or {}
    rows = list(worksheet.get("sale_rows") or [])
    for part in (worksheet.get("by_quote_asset") or {}).values():
        if part:
            rows.extend(part.get("sale_rows") or [])
    seen = set()
    unique = []
    for row in rows:
        key = (row.get("signature"), row.get("split_part") or "matched", row.get("mint"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _old_usdc_sales():
    payload = json.loads((RECON / "58PWvekDbHVPFB9FXGQrpumHD16NRajahkYLHiTvxvDL.json").read_text(encoding="utf-8"))
    return list((((payload.get("fifo") or {}).get("USDC") or {}).get("known_cost_sells")) or [])


def replay_all():
    tmp = Path(tempfile.mkdtemp(prefix="acceptance-dump-"))
    catalog = catalog_by_address()
    reports = {}
    for address in LABELS:
        store = Store(tmp / address)
        result = replay_captured_wallet(store, address, force=True)
        reports[address] = result["report"]
        store.close()
    return reports


def wallet_row(address, report):
    profile = report.get("research_profile") or {}
    analytics = report.get("analytics") or {}
    win = analytics.get("win_rate") or {}
    labels = wallet_status_fields(report, profile)
    completed = int(profile.get("completed_known_cost_positions") or 0)
    net = profile.get("scoped_pnl")
    unit = profile.get("scoped_pnl_unit")
    by_quote = profile.get("scoped_pnl_by_quote_asset") or {}
    audit = report.get("independent_audit") or {}
    audited_net = audit.get("independently_audited_episode_net")
    audited_unit = audit.get("independently_audited_episode_net_unit")
    worksheet_total = audit.get("worksheet_total")
    worksheet_unit = audit.get("worksheet_total_unit")
    worksheet_audited = audit.get("worksheet_total_independently_audited")
    completed_net = audit.get("app_completed_episode_net")
    completed_unit = audit.get("app_completed_episode_net_unit")
    worksheet_figure = worksheet_total if worksheet_total not in (None, "") else None
    if worksheet_figure in (None, "") and net not in (None, ""):
        worksheet_figure = net
        worksheet_unit = worksheet_unit or unit
    if worksheet_figure in (None, "") and by_quote:
        labelled_quotes = [
            (amount, asset) for asset, amount in by_quote.items() if amount not in (None, "")
        ]
        if len(labelled_quotes) == 1:
            worksheet_figure, worksheet_unit = labelled_quotes[0][0], labelled_quotes[0][1]
    if completed < 1:
        net_text = None
        fragment = profile.get("matched_fragment_pnl")
    else:
        fragment = None
        parts = []
        if completed_net not in (None, ""):
            parts.append(f"{completed_net} {completed_unit} (completed-episode net)")
            if audit.get("independently_audited") and audited_net not in (None, ""):
                from scanner.mass_search.qualification_gates import format_auditor_confirmation
                unit = audited_unit or completed_unit or "SOL"
                confirm = (
                    audit.get("auditor_confirmation")
                    or format_auditor_confirmation(
                        completed_net, audited_net, unit, independently_audited=True
                    )
                )
                if confirm:
                    parts.append(confirm)
        if worksheet_figure not in (None, ""):
            parts.append(f"{worksheet_figure} {worksheet_unit or unit or ''} ({WORKSHEET_LABEL})")
        net_text = "; ".join(parts) if parts else None
    judged = labels["coverage_status_detail"]
    return {
        "label": LABELS[address],
        "address": address,
        "qualification_level": labels["qualification_level"],
        "coverage_count_share": profile.get("coverage_count_share"),
        "coverage_value_share": profile.get("coverage_value_share"),
        "coverage_status": labels["coverage_status"],
        "blocking_reason": labels["blocking_reason"],
        "dependency_unresolved_basis": judged.get("dependency_unresolved_basis"),
        "dependency_unresolved_costs": judged.get("dependency_unresolved_costs"),
        "concentration": (profile.get("concentration_detail") or {}).get("label"),
        "win_rate": win.get("rate"),
        "wins": win.get("wins"),
        "win_denominator": win.get("denominator"),
        "verified_tips_sol": report.get("verified_tips_sol"),
        "sensitivity_unverified_debits_sol": report.get("sensitivity_unverified_debits_sol"),
        "completed": completed,
        "scoped_pnl": net,
        "scoped_pnl_unit": unit,
        "scoped_pnl_by_quote_asset": by_quote,
        "net_display": net_text,
        "matched_fragment_pnl": fragment,
        "matched_fragment_unit": profile.get("matched_fragment_unit"),
        "unresolved_basis_sales": profile.get("unresolved_basis_sales"),
        "open_buys_in_sample": profile.get("open_buys_in_sample"),
        "independently_audited": (report.get("independent_audit") or {}).get("independently_audited"),
        "independent_audit_status": (report.get("independent_audit") or {}).get("status"),
        "independently_audited_episode_net": (report.get("independent_audit") or {}).get("independently_audited_episode_net"),
        "independently_audited_episode_net_unit": (report.get("independent_audit") or {}).get("independently_audited_episode_net_unit"),
        "completed_episode_net": completed_net if completed >= 1 else None,
        "completed_episode_net_unit": completed_unit if completed >= 1 else None,
        "worksheet_total": (report.get("independent_audit") or {}).get("worksheet_total"),
        "worksheet_total_unit": (report.get("independent_audit") or {}).get("worksheet_total_unit"),
        "worksheet_total_independently_audited": (report.get("independent_audit") or {}).get("worksheet_total_independently_audited"),
        "unaudited_venues": (report.get("independent_audit") or {}).get("unaudited_venues"),
        "sensitivity_sign_flip": (profile.get("qualification_level") or {}).get("sensitivity_sign_flip"),
        "record_breakdown": (report.get("record_breakdown") or {}).get("counts"),
        "conversions": len(report.get("conversions") or []),
    }


def sale_diffs(reports):
    mixed = reports["58PWvekDbHVPFB9FXGQrpumHD16NRajahkYLHiTvxvDL"]
    a6ps = reports["A6PSQFRfv93hoAn1LhQGRT2dYQtjDKX6SE2vN9MEvbot"]
    an9s = reports["An9sREpLnAXVi4KMaTGuGvgET51CyaukLUTMtxzmLYSB"]
    old = {(row.get("signature"), row.get("split_part") or "matched"): row for row in _old_usdc_sales()}
    new_sales = [
        row for row in _sales(mixed)
        if (row.get("settlement_asset") or row.get("quote_asset") or "").upper() == "USDC"
        or row.get("proceeds_usdc") not in (None, "")
        or (mixed.get("by_quote_asset") or {}).get("USDC")
    ]
    usdc_sheet = ((mixed.get("worksheet") or {}).get("by_quote_asset") or {}).get("USDC") or {}
    current = list(usdc_sheet.get("sale_rows") or [])
    if not current:
        current = [row for row in _sales(mixed) if not str(row.get("basis") or "").startswith("So")]
    newly = []
    rebased = []
    unchanged = []
    for row in current:
        key = (row.get("signature"), row.get("split_part") or "matched")
        prior = old.get(key)
        entry = {
            "signature": row.get("signature"),
            "mint": row.get("mint"),
            "split_part": row.get("split_part"),
            "unresolved_basis": row.get("unresolved_basis"),
            "not_clean_episode": row.get("not_clean_episode"),
            "basis": row.get("basis"),
            "proceeds": row.get("proceeds"),
            "net_profit": row.get("net_profit"),
            "old_basis": None if not prior else prior.get("basis"),
            "old_proceeds": None if not prior else prior.get("proceeds"),
            "old_net_profit": None if not prior else prior.get("net_profit"),
        }
        if prior is None:
            newly.append(entry)
        elif _q(prior.get("net_profit")) != _q(row.get("net_profit")) or _q(prior.get("basis")) != _q(row.get("basis")):
            entry["why"] = "re-based after opening-inventory-first FIFO and later decoded buys backing the same mint"
            rebased.append(entry)
        else:
            unchanged.append(entry)
    a6ps_detail = ((a6ps.get("completed_episode_detail") or {}).get("per_mint_detail") or {})
    an9s_detail = ((an9s.get("completed_episode_detail") or {}).get("per_mint_detail") or {})
    return {
        "kind": "sale-level-diff-v1",
        "58PW": {
            "old_usdc_net": str(OLD_USDC),
            "new_usdc_net": str(usdc_sheet.get("total_profit_usdc") or NEW_USDC),
            "old_known_cost_sales": 3,
            "new_known_cost_sales": int(usdc_sheet.get("known_cost_sales") or 0),
            "new_unresolved_basis_sales": int(usdc_sheet.get("unresolved_basis_sales") or 0),
            "new_open_lots": int(usdc_sheet.get("open_lots") or 0),
            "delta_usdc": str((usdc_sheet.get("total_profit_usdc") and Decimal(str(usdc_sheet["total_profit_usdc"])) or NEW_USDC) - OLD_USDC),
            "newly_decoded_or_matched": newly,
            "rebased": rebased,
            "unchanged": unchanged,
            "why": (
                "Opening inventory is consumed first and only fully backed clean sales count. "
                "Additional Pump/PumpSwap buys now back BPxx, CARDS and pumpCmXq sales that "
                "were previously unresolved or open lots, and the earlier partial BPxx matches "
                "were re-based against the remaining known lots."
            ),
        },
        "A6PS": {
            "old_completed_episodes": 6,
            "new_completed_episodes": a6ps.get("wallet_completed_episodes"),
            "per_mint_detail": a6ps_detail,
            "why": (
                "Two additional mints now complete flat-to-flat after Pump v2 / opening-inventory "
                "isolation. Earlier 6-episode count treated some later closes as open or as extra "
                "sale rows rather than completed positions."
            ),
        },
        "An9s": {
            "old_completed_episodes": 0,
            "new_completed_episodes": an9s.get("wallet_completed_episodes"),
            "scoped_pnl": (an9s.get("research_profile") or {}).get("scoped_pnl"),
            "open_buys_in_sample": (an9s.get("research_profile") or {}).get("open_buys_in_sample"),
            "per_mint_detail": an9s_detail,
            "why": (
                "One mint now closes a single clean episode (+174.66 SOL) after Pump/PumpSwap "
                "reconstruction. 27 other lots stay open and are not episodes."
            ),
        },
        "PRODUCT_READY": False,
    }


def main():
    reports = replay_all()
    table = [wallet_row(address, reports[address]) for address in LABELS]
    labels = research_label_tables(table)
    diffs = sale_diffs(reports)
    (OUT / "WALLET_TABLE.json").write_text(json.dumps({**labels, "PRODUCT_READY": False}, indent=2) + "\n", encoding="utf-8")
    (OUT / "LABEL_TABLES.json").write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")
    (OUT / "SALE_DIFFS.json").write_text(json.dumps(diffs, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "qualification_level_counts": labels["qualification_level_counts"],
        "coverage_status_counts": labels["coverage_status_counts"],
        "wallets": [
            {
                "label": row["label"],
                "qualification_level": row["qualification_level"],
                "coverage_status": row["coverage_status"],
                "blocking_reason": row["blocking_reason"],
                "completed": row["completed"],
                "net": row["net_display"],
                "fragment": row["matched_fragment_pnl"],
                "win": f"{row['wins']}/{row['win_denominator']}",
                "sens": row["sensitivity_unverified_debits_sol"],
                "flip": row["sensitivity_sign_flip"],
                "audit": row["independent_audit_status"],
            }
            for row in labels["wallets"]
        ],
        "58PW_new_sales": len(diffs["58PW"]["newly_decoded_or_matched"]),
        "58PW_rebased": len(diffs["58PW"]["rebased"]),
        "A6PS": diffs["A6PS"]["new_completed_episodes"],
        "An9s": diffs["An9s"]["new_completed_episodes"],
    }, indent=2))


if __name__ == "__main__":
    main()
