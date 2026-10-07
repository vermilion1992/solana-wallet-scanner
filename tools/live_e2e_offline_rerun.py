#!/usr/bin/env python3
"""Offline Phase 4 + pre-screen ranking over attached live raw pages.

No provider calls. Keys must stay unset. Writes evidence tables only.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner.investigation import (
    DECODER_VERSION,
    DFLOW,
    GMGN,
    JUPITER,
    PHOTON,
    PUMP,
    PUMP_SWAP,
    decode_supported_swaps,
)
from scanner.mass_search.adapters import SourceError
from scanner.mass_search.bundle_detect import detect_bundle_or_distribution
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.live_e2e import (
    AUTHORIZATION_ID_NEXT,
    HARD_CEILINGS,
    _verify_saved_page,
    assess_history_completeness,
    classify_programs,
    compute_bot_rate,
    estimate_phase3_pages,
    page_sort_key,
    phase4_offline,
    plan_request_counts,
    prescreen_rank_score,
    unwrap_gta_record,
)
from scanner.storage import Store
import tools.independent_episode_audit as auditor

RAW_ROOTS = [
    Path("/tmp/live-raw-f635a45/live-out/main/raw"),
    Path("/tmp/live-raw-06cea26/live-out/main/raw"),
    Path("/tmp/live-raw-both/live-e2e-cfe6e78/live-out/raw"),
    Path("/tmp/live-raw-both/live-e2e-bbc5bef/live-out/raw"),
]
EVIDENCE = ROOT / "evidence/mass-wallet-funnel/live-e2e-proof-2026-10-07"
MAX_BOT_RATE = Decimal("25")
FULL_HISTORY_SLOTS = 25
BOUNDS = {
    "report_start_inclusive": "2026-09-07T10:52:20Z",
    "report_end_exclusive": "2026-10-07T10:52:20Z",
    "history_start_inclusive": "2026-07-09T10:52:20Z",
}


def _iso_to_unix(text):
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def _wallet_dirs(phase):
    found = {}
    for root in RAW_ROOTS:
        phase_dir = root / f"phase{phase}"
        if not phase_dir.is_dir():
            continue
        for wallet_dir in phase_dir.iterdir():
            if wallet_dir.is_dir() and not wallet_dir.name.startswith("."):
                found.setdefault(wallet_dir.name, []).append(wallet_dir)
    return found


def _load_pages(wallet_dirs):
    records_by_page = {}
    blocked = None
    for wallet_dir in wallet_dirs:
        for path in sorted(wallet_dir.glob("page*.bin"), key=page_sort_key):
            index = path.name[4:-4]
            try:
                _raw, data, _token = _verify_saved_page(path, f"{wallet_dir}/{path.name}")
            except SourceError as error:
                blocked = str(error)
                continue
            records_by_page.setdefault(index, data)
    pages = [records_by_page[key] for key in sorted(records_by_page, key=lambda item: int(item) if item.isdigit() else item)]
    records = []
    for page in pages:
        records.extend(page)
    return records, pages, blocked, len(records_by_page)


def _has_known_basis_buys(sample_records, address):
    try:
        decoded = decode_supported_swaps(canonical_decode_records(sample_records), address)
        return any(event.get("kind") == "buy" for event in decoded.get("events") or [])
    except Exception:
        return False


def _prescreen_row(address, phase2_dirs):
    records, pages, blocked, page_count = _load_pages(phase2_dirs)
    if blocked and not records:
        return {
            "address": address,
            "blocked": True,
            "blocker": blocked,
            "bundle": None,
            "bundle_reasons": [],
            "bot": None,
            "bot_rate": None,
            "has_known_basis_buys": False,
            "supported_venue_value_share": None,
            "coverability_rank_key": "0",
            "dropped": True,
            "drop_reason": "page_integrity_blocked",
            "chosen_for_full_history": False,
            "source_runs": [str(path) for path in phase2_dirs],
            "pages": page_count,
        }
    sigs = pages[0] if pages else []
    sample = pages[1] if len(pages) > 1 else (pages[0] if pages else records)
    programs = classify_programs(sample, address)
    bot_rate = compute_bot_rate(sigs, 30)
    bundle = detect_bundle_or_distribution(sample, address)
    has_buys = _has_known_basis_buys(sample, address)
    bot = bot_rate > MAX_BOT_RATE
    dropped = False
    drop_reason = None
    if bundle.get("excluded"):
        dropped = True
        drop_reason = bundle.get("reason") or "bundle_or_distribution"
    elif bot:
        dropped = True
        drop_reason = "bot_rate"
    elif not has_buys:
        dropped = True
        drop_reason = "no_known_basis_buys"
    score = prescreen_rank_score({
        "supported_venue_value_share": programs.get("supported_venue_value_share") or "0",
        "has_known_basis_buys": has_buys,
        "bundle": bundle.get("excluded"),
        "bot": bot,
    })
    return {
        "address": address,
        "blocked": bool(blocked),
        "blocker": blocked,
        "in_window_tx_count": len(sigs),
        "sample_records": len(sample),
        "decodable_share": programs.get("decodable_share"),
        "supported_venue_value_share": programs.get("supported_venue_value_share"),
        "has_known_basis_buys": has_buys,
        "bundle": bundle.get("excluded"),
        "bundle_reasons": bundle.get("reasons") or [],
        "bot": bot,
        "bot_rate": str(bot_rate),
        "program_blockers": programs.get("blockers") or [],
        "coverability_rank_key": str(score),
        "dropped": dropped,
        "drop_reason": drop_reason,
        "chosen_for_full_history": False,
        "source_runs": [str(path) for path in phase2_dirs],
        "pages": page_count,
        "PRODUCT_READY": False,
    }


def _audit(address, records):
    auditor.REPORT_START = _iso_to_unix(BOUNDS["report_start_inclusive"])
    auditor.REPORT_END = _iso_to_unix(BOUNDS["report_end_exclusive"])
    auditor.ACQUISITION = _iso_to_unix(BOUNDS["history_start_inclusive"])
    trades = []
    for record in records:
        event = auditor.reconstruct_record(record, address)
        if event:
            trades.append(event)
    episodes, unresolved, known_sales = auditor._fifo(trades)
    net, unit, by_unit = auditor.episode_net_totals(episodes)
    return {
        "clean_episodes": len(episodes),
        "independently_audited_episode_net": net,
        "independently_audited_episode_net_unit": unit,
        "independently_audited_episode_nets_by_unit": by_unit,
        "unresolved_basis_sales": unresolved,
        "known_cost_sales": known_sales,
        "reconstructed_trades": len(trades),
    }


def _phase4(phase3_dirs):
    tmp = Path(tempfile.mkdtemp(prefix="live-e2e-phase4-"))
    store = Store(tmp / "store")
    wallets = sorted(phase3_dirs)
    state = {"phase3": {}}
    out = tmp / "out"
    for address, dirs in phase3_dirs.items():
        dest = out / "raw" / "phase3" / address
        dest.mkdir(parents=True)
        pages = 0
        for wallet_dir in dirs:
            for path in wallet_dir.glob("page*.bin"):
                target = dest / path.name
                if not target.exists():
                    shutil.copy2(path, target)
                    integrity = path.with_name(path.name + ".integrity.json")
                    if integrity.is_file():
                        shutil.copy2(integrity, dest / integrity.name)
                    pages += 1
        leftover = None
        dest_pages = sorted(dest.glob("page*.bin"), key=page_sort_key)
        if dest_pages:
            try:
                _raw, _data, leftover = _verify_saved_page(dest_pages[-1])
            except SourceError:
                leftover = None
        state["phase3"][address] = {
            "pages": pages,
            "done": True,
            "pagination_token": leftover,
            "leftover_pagination_token": bool(leftover),
        }
    config = {
        "phases": (4,),
        "wallets": wallets,
        "output_dir": str(out),
        "bounds": BOUNDS,
        "authorization_id": AUTHORIZATION_ID_NEXT,
    }
    result = phase4_offline(store, config, state)
    store.close()
    rows = {row["address"]: row for row in result.get("wallets") or []}
    for address, dirs in phase3_dirs.items():
        records, _pages, _blocked, _count = _load_pages(dirs)
        rows.setdefault(address, {"address": address})
        rows[address]["auditor"] = _audit(address, records) if records else {
            "clean_episodes": 0,
            "independently_audited_episode_net": None,
            "independently_audited_episode_net_unit": None,
            "independently_audited_episode_nets_by_unit": None,
            "unresolved_basis_sales": 0,
            "known_cost_sales": 0,
            "reconstructed_trades": 0,
        }
        rows[address]["phase3_pages"] = state["phase3"][address]["pages"]
    shutil.rmtree(tmp, ignore_errors=True)
    return rows


JXT = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
VENUE_LABELS = {
    JUPITER: "jupiter",
    PUMP: "pump",
    PUMP_SWAP: "pumpswap",
    GMGN: "gmgn",
    DFLOW: "dflow",
    PHOTON: "photon",
    "G2GMMDKkw3LXXNRNLyLMy3myki3yi7tjdyxbBbGrBqrg": "g2gmmdk",
    "pumpapii17v9uhRiokHwhG3yWYtB6hgJRmsSC5p5bb2": "pumpapi",
    "DGMgNKpqygARV2pHZfW4kNQSHT9F3Ly2BKWqvpYrAg5C": "dgmgnkpq",
}


def _flag_verdict(row):
    reasons = list(row.get("bundle_reasons") or row.get("phase4_bundle_reasons") or [])
    pair = row.get("controlled_pair") or []
    parts = []
    if "controlled_pair" in reasons or pair:
        expl = row.get("controlled_pair_explanation") or "closed-loop / sweep co-signer"
        parts.append(f"controlled_pair (not a lead): {expl}")
    if "multi_signer_bundle_buy" in reasons:
        parts.append("bundle: material same-swap partner (keep)")
    if "sell_proceeds_to_cosigner" in reasons:
        parts.append("proceeds to material co-signer")
    if "transfer_in_zero_basis" in reasons:
        parts.append("unknown/zero basis (later-sold or gifted mint)")
    if not parts:
        parts.append("no exclusion flag")
    return "; ".join(parts)


def _outer_programs(record):
    raw = unwrap_gta_record(record)
    if not isinstance(raw, dict):
        return []
    message = ((raw.get("transaction") or {}).get("message") or {})
    labels = []
    for ix in message.get("instructions") or []:
        if not isinstance(ix, dict):
            continue
        program = ix.get("programId") or ix.get("programIdIndex")
        if isinstance(program, str) and len(program) >= 8:
            labels.append(VENUE_LABELS.get(program, program[:8]))
    return labels


def _classify_uncovered(address, records):
    decoded = decode_supported_swaps(canonical_decode_records(records), address)
    events = decoded.get("events") or []
    coverage = decoded.get("coverage") or {}
    buy_sell = [event for event in events if event.get("kind") in ("buy", "sell")]
    decoded_sigs = {event.get("signature") for event in buy_sell}
    by_cause = {}
    uncovered = []
    for record in records:
        raw = unwrap_gta_record(record)
        if not isinstance(raw, dict):
            continue
        sig = ((raw.get("transaction") or {}).get("signatures") or [None])[0] or record.get("signature")
        if not sig or sig in decoded_sigs:
            continue
        programs = _outer_programs(raw)
        reason = None
        for issue in coverage.get("unsupported_transactions") or []:
            if issue.get("signature") == sig:
                reason = issue.get("reason")
                break
        if reason is None:
            for event in events:
                if event.get("signature") == sig and event.get("kind") == "unsupported":
                    reason = event.get("reason")
                    break
        venue = next((name for name in programs if name in VENUE_LABELS.values()), None)
        if venue is None and programs:
            venue = programs[0]
        if reason is None:
            if not programs:
                reason = "no_outer_program"
            elif all(name in ("system", "ComputeB", "11111111") or name.startswith("Token") or name.startswith("AToken") for name in programs):
                reason = "transfer_or_admin"
            else:
                reason = "undecoded_outer"
        cause = f"{venue or 'unknown'}: {reason}"
        by_cause[cause] = by_cause.get(cause, 0) + 1
        uncovered.append({"signature": sig, "venue": venue, "reason": reason, "programs": programs[:6]})
    return {
        "decoder_version": coverage.get("decoder_version") or DECODER_VERSION,
        "transactions": coverage.get("transactions") or len(records),
        "decoded_swaps": coverage.get("decoded_swaps"),
        "buy_sell_events": len(buy_sell),
        "uncovered_tx_count": len(uncovered),
        "uncovered_by_cause": dict(sorted(by_cause.items(), key=lambda item: (-item[1], item[0]))),
        "uncovered_sample": uncovered[:40],
        "unsupported_tx_count": coverage.get("unsupported_tx_count"),
        "decoded_unresolved_cash_count": coverage.get("decoded_unresolved_cash_count"),
    }


def _plan():
    kept = {f"W{i:02d}": {"address": f"W{i:02d}", "dropped": i >= FULL_HISTORY_SLOTS} for i in range(100)}
    return plan_request_counts({
        "wallets": [f"W{i:02d}" for i in range(100)],
        "phases": (1, 2, 3, 4),
        "discovery": True,
        "caps": dict(HARD_CEILINGS),
    }, state={"phase2": kept})


def main():
    forbidden = ("HELIUS_API_KEY", "BIRDEYE_API_KEY", "HELIUS_API_KEYS", "HELIUS_RPC_URL")
    leaked = [key for key in forbidden if os.environ.get(key)]
    if leaked:
        raise SystemExit(f"refusing to run with provider env set: {leaked}")

    phase2 = _wallet_dirs(2)
    phase3 = _wallet_dirs(3)
    prescreen = [_prescreen_row(address, dirs) for address, dirs in sorted(phase2.items())]
    ranked = sorted(prescreen, key=lambda row: (
        row.get("dropped") is True,
        -float(row.get("coverability_rank_key") or 0),
        row["address"],
    ))
    chosen = []
    for row in ranked:
        if row.get("dropped"):
            continue
        if float(row.get("coverability_rank_key") or 0) <= 0:
            continue
        if len(chosen) >= FULL_HISTORY_SLOTS:
            break
        row["chosen_for_full_history"] = True
        chosen.append(row["address"])

    phase4_rows = _phase4(phase3) if phase3 else {}
    wallets = []
    seen = set()
    for row in ranked:
        address = row["address"]
        seen.add(address)
        extra = phase4_rows.get(address) or {}
        merged = dict(row)
        if extra.get("bundle") is not None:
            merged["phase4_bundle"] = extra.get("bundle")
            merged["phase4_bundle_reasons"] = extra.get("bundle_reasons") or []
            merged["bundle"] = extra.get("bundle")
            merged["bundle_reasons"] = extra.get("bundle_reasons") or []
        if extra.get("controlled_pair"):
            merged["controlled_pair"] = extra.get("controlled_pair")
            merged["controlled_pair_explanation"] = extra.get("controlled_pair_explanation")
        for key, value in extra.items():
            if key in ("address", "bundle", "bundle_reasons", "has_known_basis_buys", "bot",
                       "bot_rate", "supported_venue_value_share", "coverability_rank_key",
                       "dropped", "drop_reason"):
                continue
            if value is None and merged.get(key) is not None:
                continue
            merged[key] = value
        wallets.append(merged)
    for address, extra in sorted(phase4_rows.items()):
        if address in seen:
            continue
        wallets.append({
            "address": address,
            "dropped": False,
            "chosen_for_full_history": False,
            **extra,
        })

    jxt_dirs = phase3.get(JXT) or phase2.get(JXT) or []
    jxt_records, _jxt_pages, _jxt_blocked, jxt_page_count = _load_pages(jxt_dirs) if jxt_dirs else ([], [], None, 0)
    jxt_uncovered = _classify_uncovered(JXT, jxt_records) if jxt_records else None
    jxt_row = next((row for row in wallets if row.get("address") == JXT), None)
    if jxt_row and jxt_uncovered:
        jxt_row["jxt_uncovered"] = {
            "uncovered_tx_count": jxt_uncovered["uncovered_tx_count"],
            "uncovered_by_cause": jxt_uncovered["uncovered_by_cause"],
            "decoder_version": jxt_uncovered["decoder_version"],
            "buy_sell_events": jxt_uncovered["buy_sell_events"],
        }

    plan = _plan()
    payload = {
        "kind": "live-e2e-phase4-offline-rerun-v2",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bounds": BOUNDS,
        "max_bot_rate": str(MAX_BOT_RATE),
        "full_history_slots": FULL_HISTORY_SLOTS,
        "wallet_count": len(wallets),
        "phase2_wallets": len(phase2),
        "phase3_wallets": len(phase3),
        "chosen_for_full_history": chosen,
        "chosen_count": len(chosen),
        "plan": plan,
        "plan_fits": (
            plan["totals"]["birdeye_requests"] <= HARD_CEILINGS["birdeye_requests"]
            and plan["totals"]["birdeye_units"] <= HARD_CEILINGS["birdeye_units"]
            and plan["totals"]["helius_requests"] <= HARD_CEILINGS["helius_requests"]
            and plan["totals"]["helius_units"] <= HARD_CEILINGS["helius_units"]
        ),
        "wallets": wallets,
        "jxt_uncovered": jxt_uncovered,
        "jxt_pages": jxt_page_count,
        "PRODUCT_READY": False,
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "PHASE4_OFFLINE_RERUN.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md = EVIDENCE / "PHASE4_OFFLINE_RERUN.md"
    lines = [
        "# Offline Phase 4 replay (all four live-run attached pages)",
        "",
        f"Bounds: report `{BOUNDS['report_start_inclusive']}` → `{BOUNDS['report_end_exclusive']}`; "
        f"history start `{BOUNDS['history_start_inclusive']}`.",
        f"{len(phase3)} Phase-3 wallets. `max_bot_rate`={MAX_BOT_RATE}/day. PRODUCT_READY false. No live calls.",
        f"Decoder `{DECODER_VERSION}`.",
        "",
        "## Phase 4 replay",
        "",
        "| Wallet | history_complete | Bundle / pair flags | controlled_pair | Flag verdict | Venue share | Cov count / value | In-window completed | Realized P&L | Auditor clean / net | App − auditor | Lead | Blocker |",
        "|---|---|---|---|---|---:|---|---:|---|---|---|---|---|",
    ]
    for row in wallets:
        if not row.get("completed_trades") and row.get("auditor") is None and not row.get("phase3_pages"):
            continue
        if not row.get("phase3_pages") and row.get("completed_trades") in (None, 0) and not (row.get("auditor") or {}).get("clean_episodes"):
            if row.get("address") not in phase3:
                continue
        addr = row["address"]
        short = addr[:8]
        hist = row.get("history_complete")
        reason = row.get("history_complete_reason") or ""
        hist_txt = f"{'yes' if hist else 'no'}" + (f" ({reason})" if reason else "")
        flags = ",".join(row.get("bundle_reasons") or row.get("phase4_bundle_reasons") or []) or "none"
        pair = ",".join(row.get("controlled_pair") or []) or "—"
        verdict = _flag_verdict(row)
        venue = row.get("supported_venue_value_share") or "—"
        cov = f"{row.get('coverage_count_share') or '—'} / {row.get('coverage_value_share') or '—'}"
        completed = row.get("completed_trades")
        pnl = row.get("realized_pnl_sol")
        aud = row.get("auditor") or {}
        aud_txt = "—"
        delta = "—"
        if aud.get("clean_episodes") not in (None, 0) or aud.get("independently_audited_episode_net") not in (None, ""):
            aud_txt = f"{aud.get('clean_episodes')} / {aud.get('independently_audited_episode_net')}"
            if pnl not in (None, "") and aud.get("independently_audited_episode_net") not in (None, ""):
                try:
                    delta = str(Decimal(str(pnl)) - Decimal(str(aud["independently_audited_episode_net"])))
                except Exception:
                    delta = "—"
        lines.append(
            f"| `{short}` | {hist_txt} | {flags} | {pair} | {verdict} | {venue} | {cov} | {completed} | {pnl} | {aud_txt} | {delta} | "
            f"{row.get('lead_level') or '—'} | {row.get('blocker') or '—'} |"
        )
    if jxt_row:
        lines.extend([
            "",
            "## jXtCVtdQ after Jupiter native-settle + Token-2022 skip",
            "",
            f"Pages: {jxt_page_count}. Decoder `{((jxt_uncovered or {}).get('decoder_version'))}`.",
            f"Coverage count/value: `{jxt_row.get('coverage_count_share')}` / `{jxt_row.get('coverage_value_share')}`.",
            f"App completed trades: `{jxt_row.get('completed_trades')}`; realized P&L SOL: `{jxt_row.get('realized_pnl_sol')}`.",
            f"pnl_scope: `{jxt_row.get('pnl_scope')}`. {jxt_row.get('pnl_note') or ''}",
            f"Auditor: `{((jxt_row.get('auditor') or {}).get('clean_episodes'))}` clean / "
            f"`{((jxt_row.get('auditor') or {}).get('independently_audited_episode_net'))}` net; "
            f"unresolved sales `{((jxt_row.get('auditor') or {}).get('unresolved_basis_sales'))}`.",
            f"Flags: `{','.join(jxt_row.get('bundle_reasons') or []) or 'none'}`. "
            f"controlled_pair: `{','.join(jxt_row.get('controlled_pair') or []) or 'none'}`.",
            f"Buy/sell events decoded: `{(jxt_uncovered or {}).get('buy_sell_events')}`. "
            f"Uncovered txs: `{(jxt_uncovered or {}).get('uncovered_tx_count')}`.",
            "",
            "Uncovered tx causes (venue: reason → count):",
            "",
        ])
        for cause, count in ((jxt_uncovered or {}).get("uncovered_by_cause") or {}).items():
            lines.append(f"- `{cause}`: {count}")
        if not (jxt_uncovered or {}).get("uncovered_by_cause"):
            lines.append("- none")
        lines.extend([
            "",
            "App-vs-auditor gap is decoded-subset FIFO vs full balance-delta. Remaining uncovered "
            "outers (pumpapi / G2GMMDK / transfers) are not Jupiter; those episodes stay in the auditor "
            "and out of app P&L.",
        ])
    lines.extend(["", f"JSON: `{out.relative_to(ROOT)}`", ""])
    md.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({
        "wallets": len(wallets),
        "phase2": len(phase2),
        "phase3": len(phase3),
        "chosen": len(chosen),
        "plan_fits": payload["plan_fits"],
        "plan": plan["totals"],
        "jxt_uncovered": (jxt_uncovered or {}).get("uncovered_tx_count"),
        "jxt_buy_sell": (jxt_uncovered or {}).get("buy_sell_events"),
        "jxt_coverage": {
            "count": (jxt_row or {}).get("coverage_count_share"),
            "value": (jxt_row or {}).get("coverage_value_share"),
            "completed": (jxt_row or {}).get("completed_trades"),
            "pnl": (jxt_row or {}).get("realized_pnl_sol"),
        },
        "out": str(out),
        "md": str(md),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
