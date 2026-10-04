#!/usr/bin/env python3
"""Replay sanitized receipts and pure local decoders; no network/key access."""
from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LIVE = HERE / "live"
PLAN_HASH = "c3b78e505e9052da901af9e29c6556a993ff147affad4b735083954182ee432f"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, label):
    if not condition:
        raise ValueError(label)


def utc(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def main():
    result_bytes = (LIVE / "result.json").read_bytes()
    result = json.loads(result_bytes)
    plan_bytes = (ROOT / "evidence/product-milestone/SOURCE_PROBE_PLAN.json").read_bytes()
    require(digest(plan_bytes) == PLAN_HASH == result["approved_plan_sha256"], "Exact approved plan hash")
    plan = json.loads(plan_bytes)
    require(result["state"] == "OBSERVED_IN_SCOPE", "Observed scoped completion")
    require(result["request_cap"] == 10 and result["credit_cap"] == 100, "Approved independent caps")
    require(result["retries"] == 0 and result["purchases"] is False and result["quota_reset"] is False, "No retries/purchases/reset")
    rows = result["requests"]
    require(len(rows) == result["provider_requests"] == 10, "Ten retained attempt receipts")
    require([r["id"] for r in rows] == [r["id"] for r in plan["requests"]], "Exact planned request order")
    require(len({r["reservation"] for r in rows}) == 10, "Distinct durable reservations")
    require(sum(r["conservative_credits"] for r in rows) == result["conservative_credits"] == 73, "Reservation credit reconciliation")
    before, after = result["quota_before"], result["quota_after"]
    require(before["used"] == 0 and before["reserved"] == 0 and after["used"] == 73 and after["reserved"] == 0, "Sanitized ledger reconciliation")
    require(after["remaining"] == 27 and after["cap"] == 100, "Durable remaining budget")
    require(result["confirmation"] == json.loads((HERE / "DASHBOARD_CONFIRMATION.json").read_bytes()), "Confirmed dashboard binding")
    require(result["billing_actual_credits"] is None, "Actual billing is not asserted")
    artifacts = result["artifacts"]
    require(set(artifacts) == {p.name for p in LIVE.iterdir() if p.is_file() and p.name != "result.json"}, "Complete live artifact index")
    checked_artifacts = []
    for name, binding in sorted(artifacts.items()):
        require(Path(name).name == name, "Artifact basename path")
        raw = (LIVE / name).read_bytes()
        require(digest(raw) == binding["sha256"] and len(raw) == binding["bytes"], "Artifact compressed/raw hash and size: " + name)
        checked_artifacts.append(name)
    responses = {}
    page_observations = {}
    primary_observations = {}
    current_observations = {}
    prior_cursor = None
    all_seen = set()
    for number, (row, approved) in enumerate(zip(rows, plan["requests"]), 1):
        request_bytes = (LIVE / row["request_path"]).read_bytes()
        require(digest(request_bytes) == row["request_sha256"], "Exact request hash")
        request = json.loads(request_bytes)
        expected_params = json.loads(json.dumps(approved["params"]))
        if approved["id"] == "all-continuation":
            expected_params[1]["paginationToken"] = prior_cursor
        require(request == {"jsonrpc": "2.0", "id": number, "method": approved["method"], "params": expected_params}, "Exact request body/conditional cursor")
        raw = gzip.decompress((LIVE / row["response_path"]).read_bytes())
        require(digest(raw) == row["response_sha256"] and len(raw) == row["response_bytes"], "Decompressed retained response binding")
        require(len(raw) <= 32 * 1024 * 1024, "Bounded response size")
        response = json.loads(raw)
        require(row["http_status"] == 200 and row["state"] == "OBSERVED", "HTTP and producer assessment state")
        require(response.get("jsonrpc") == "2.0" and type(response.get("id")) is int and response["id"] == number and response.get("error") is None and "result" in response, "Independent RPC envelope/identity")
        value = response["result"]
        responses[row["id"]] = value
        method = row["method"]
        if method == "getTransactionsForAddress":
            require(type(value) is dict and type(value.get("data")) is list and "paginationToken" in value, "Full indexed schema")
            txs, cursor = value["data"], value["paginationToken"]
            require(len(txs) == 100, "Observed approved row bound")
            require(type(cursor) is str and len(cursor.split(":")) == 2 and all(p.isdigit() for p in cursor.split(":")), "Explicit observed nonterminal cursor")
            positions = [(x["slot"], x["transactionIndex"]) for x in txs]
            signatures = [x["transaction"]["signatures"][0] for x in txs]
            require(all(type(v) is int and v >= 0 for pos in positions for v in pos), "Indexed canonical position types")
            require(positions == sorted(positions) and len(set(positions)) == 100 and len(set(signatures)) == 100, "Page order/position/signature uniqueness")
            bounds = approved["params"][1]["filters"]["blockTime"]
            require(all(type(x["blockTime"]) is int and bounds["gte"] <= x["blockTime"] < bounds["lt"] for x in txs), "Exact half-open interval membership")
            require(all(x.get("version") == 0 and type(x.get("meta")) is dict and "err" in x["meta"] for x in txs), "Observed v0/execution schema only")
            require(tuple(map(int, cursor.split(":"))) == positions[-1], "Cursor agrees with last retained canonical position")
            if row["id"] == "all-index":
                prior_cursor = cursor
                all_seen.update(signatures)
            elif row["id"] == "all-continuation":
                require(positions[0] > tuple(map(int, prior_cursor.split(":"))) and cursor != prior_cursor, "Continuation advances beyond frozen cursor")
                require(not all_seen.intersection(signatures), "No repeated all-page signature")
                all_seen.update(signatures)
            times = [x["blockTime"] for x in txs]
            require(row["assessment"]["signatures"] == signatures and row["assessment"]["cursor"] == cursor, "Producer summary bound to actual bytes")
            page_observations[row["id"]] = {"rows": len(txs), "failed_transactions": sum(x["meta"]["err"] is not None for x in txs), "versions_observed": [0], "first_position": positions[0], "last_position": positions[-1], "first_time_utc": utc(min(times)), "last_time_utc": utc(max(times)), "cursor": cursor, "terminal": False}
        elif method == "getTransaction":
            expected_path = ROOT / "evidence/runs/real-cache/archives" / (approved["archived_control_hash"] + ".json.gz")
            expected_bytes = gzip.decompress(expected_path.read_bytes())
            require(digest(expected_bytes) == approved["archived_control_hash"], "Archived primary raw control hash")
            expected = json.loads(expected_bytes)
            expected = expected.get("result", expected)
            require(value["transaction"]["signatures"][0] == approved["params"][0], "Primary signature")
            require(all(value[field] == expected[field] for field in ("slot", "blockTime")), "Primary archived identity/time control")
            require(all(value["meta"][field] == expected["meta"][field] for field in ("err", "fee", "preBalances", "postBalances")), "Primary archived execution/native control")
            primary_observations[row["id"]] = {"slot": value["slot"], "time_utc": utc(value["blockTime"]), "failed": value["meta"]["err"] is not None, "fee_lamports": value["meta"]["fee"], "matched_control_fields": ["signature", "slot", "blockTime", "meta.err", "meta.fee", "meta.preBalances", "meta.postBalances"], "control_hash": approved["archived_control_hash"]}
        elif method == "getTokenAccountsByOwner":
            require(type(value) is dict and type(value["context"]["slot"]) is int and type(value["value"]) is list, "Current inventory schema")
            entries = value["value"]
            require(len({x["pubkey"] for x in entries}) == len(entries), "Current account uniqueness")
            require(all(x["account"]["data"]["parsed"]["info"]["owner"] == plan["wallet"] for x in entries), "Current wallet owner match")
            require(all(x["account"]["owner"] == approved["params"][1]["programId"] for x in entries), "Current token program owner match")
            require(all(type(x["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]) is str and x["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"].isdigit() for x in entries), "Current exact quantity string availability")
            current_observations[row["id"]] = {"accounts": len(entries), "distinct_mints": len({x["account"]["data"]["parsed"]["info"]["mint"] for x in entries}), "context_slot": value["context"]["slot"], "scope": "Current owner/program snapshot; no historical lifecycle or hidden-account proof."}
        elif method == "getSlot":
            require(type(value) is int and value >= 0, "Finalized slot type")
        else:
            raise ValueError("Unapproved method")
    require(responses["direct-index"]["data"] == responses["all-index"]["data"], "Observed direct/all first page equality")
    all_txs = responses["all-index"]["data"] + responses["all-continuation"]["data"]
    times = [x["blockTime"] for x in all_txs]
    failed = sum(x["meta"]["err"] is not None for x in all_txs)
    require(len(all_seen) == 200 and failed == 184 and max(times) - min(times) == 78, "Independently counted unique sample")
    outer_shapes, inner_shapes, key_shapes, successful_outer_programs = Counter(), Counter(), Counter(), Counter()
    for tx in all_txs:
        message, meta = tx["transaction"]["message"], tx["meta"]
        key_shapes[type(message["accountKeys"][0]).__name__] += 1
        keys = message["accountKeys"] + meta.get("loadedAddresses", {}).get("writable", []) + meta.get("loadedAddresses", {}).get("readonly", [])
        for instruction in message["instructions"]:
            outer_shapes[",".join(sorted(instruction))] += 1
            if meta["err"] is None:
                successful_outer_programs[keys[instruction["programIdIndex"]]] += 1
        for group in meta.get("innerInstructions") or []:
            for instruction in group["instructions"]:
                inner_shapes[",".join(sorted(instruction))] += 1
    sys.path.insert(0, str(ROOT))
    # These existing functions are pure observation decoders. This replay is not
    # archive import or accepted source binding; page hashes identify raw excerpt
    # provenance and do not manufacture independently fetched primary records.
    from scanner.decoder import decode_transactions
    from scanner.investigation import decode_supported_swaps
    wrappers = []
    for row in rows:
        if row["id"] in ("all-index", "all-continuation"):
            wrappers.extend({"signature": x["transaction"]["signatures"][0], "raw": x,
                             "evidence_hash": row["response_sha256"], "transaction_index": x["transactionIndex"]}
                            for x in responses[row["id"]]["data"])
    decoder_replays = {}
    for name, decoder in (("ordinary", decode_transactions), ("spot", decode_supported_swaps)):
        decoded = decoder(wrappers, plan["wallet"])
        kinds = Counter(x["kind"] for x in decoded["events"])
        reasons = Counter(x["reason"] for x in decoded.get("unresolved", []))
        require(kinds["fee"] == 200 and kinds["buy"] == 0 and kinds["sell"] == 0, "Observed sample preserves fees without manufacturing financial trades")
        decoder_replays[name] = {"event_counts": dict(kinds), "unresolved_reasons": dict(reasons)}
    receipt = {
        "kind": "distinct-read-only-bounded-source-probe-review", "state": "PASS_IN_SCOPE",
        "reviewed_utc": datetime.now(timezone.utc).isoformat(),
        "reviewed_repository_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "approved_plan_sha256": PLAN_HASH, "live_result_sha256": digest(result_bytes),
        "replay_script_sha256": digest(Path(__file__).read_bytes()),
        "network_calls": 0, "credential_lookups": 0, "application_source_modified": False,
        "checks": {"artifact_files_verified": len(checked_artifacts), "gzip_responses_decompressed_and_verified": 10, "request_bodies_exactly_matched": 10, "independent_schema_replays": 10, "primary_archive_controls_matched": 4, "distinct_reservation_receipts": 10, "producer_reservations_sum": 73, "actual_billing_delta_verified": False},
        "budget": {"requests": 10, "approved_request_cap": 10, "conservative_credits": 73, "approved_credit_cap": 100, "actual_provider_billed_credits": None, "retries": 0, "purchases": False, "quota_before": before, "quota_after": after},
        "indexed_observations": page_observations, "primary_controls": primary_observations,
        "current_inventory_observations": current_observations,
        "unique_all_page_sample": {"transactions": 200, "failed": failed, "successful": 200 - failed, "first_time_utc": utc(min(times)), "last_time_utc": utc(max(times)), "elapsed_seconds": max(times) - min(times), "direct_first_page_equals_all_first_page": True, "terminal_history_page_reached": False},
        "indexed_instruction_shape": {"account_key_container_counts": dict(key_shapes), "outer_instruction_shapes": dict(outer_shapes), "inner_instruction_shapes": dict(inner_shapes), "successful_outer_program_occurrences": dict(successful_outer_programs), "scope": "Raw compiled instructions, not jsonParsed token/system operation semantics."},
        "financial_decoder_development_replays": decoder_replays,
        "separate_conclusions": {
            "authentication_entitlement": "OBSERVED: the supplied account/key successfully served all ten exact approved requests despite retained documentation describing indexed history as Developer+; this is empirical access for this account/time, not a future Free entitlement guarantee.",
            "endpoint_support": "OBSERVED: getTransactionsForAddress full finalized status:any tokenAccounts:none/all, one pagination continuation, four getTransaction controls, both current token-program inventories and getSlot returned HTTP200/RPC results.",
            "schema_compatibility": "OBSERVED envelope/version/time/order/indexed compiled-instruction/current-inventory compatibility for these retained v0 responses only; no observed legacy/v1 compatibility conclusion. Financial decoder compatibility is not established: the200indexed records use compiled instructions, and all16successful records use an unreviewed outer route, so current spot decoding keeps them unsupported.",
            "history_depth_coverage": "PARTIAL: indexed records exist at July4 interval start and exact archived controls near Oct2 match; only 200 unique ascending indexed records spanning78seconds retained, both all-page cursors nonterminal. Complete90day/28day history is unproved.",
            "failed_transaction_coverage": "OBSERVED184failed indexed records among200unique plus four matched failed primary controls; status:any includes failures in the observed sample. Complete failed population is unproved.",
            "historical_token_ownership_lifecycle": "INCONCLUSIVE: current84964account observations are not a historical population witness. Direct/all first page equality does not establish closed/reassigned-account inclusion; no independent historical lifecycle control exists.",
            "wallet_qualification": "NOT_ASSESSED; no complete acquisition/basis/classification/valuation corpus, no complete financial ledger or B3 acceptance.",
            "remaining_unknowns": ["Terminal historical population across full report/28day/90day scopes", "Closed/reassigned account historical inclusion and lifecycle ownership", "All acquisition origins/cost basis and economic flows", "Historical eligible-asset classifications and boundary valuations", "Actual billed usage delta and lasting Free entitlement"]
        },
        "acceptance_corpus_suitability": {"recommendation": "Do not use this wallet as the first bounded complete B3 acceptance corpus. Keep as partial source-feasibility evidence and select a genuinely low-activity research wallet under an explicit separately approved collection scope.", "observed_reasons": ["84964current token accounts", "200unique indexed records span only78seconds", "Nonterminal continuation after200records", "Missing independently known lifecycle controls"], "no_total_history_or_cost_extrapolation": True, "no_scamming_or_profitability_label_inferred": True},
        "source_decision": {"bounded_source_development": "EMPIRICAL_GO for exact observed methods/account now; no more live calls are authorised by this exhausted10requestprobe.", "full_wallet_acceptance": "NO_GO until lifecycle/population controls, terminal intervals and basis/cost/classification/valuation evidence meet explicit metric dependencies.", "missing_B2_implementation": ["Accepted indexed page/raw record ingestion with original-byte/provenance/cursor/chronology binding", "Reviewed compiled system/token instruction normalization, or separately budgeted jsonParsed inputs", "Reviewed supported outer-route and economic-flow roles; the observed custom route cannot be inferred solely from inner DEX calls"]},
        "B1": "LIVE_ACCESS_AND_SAMPLE_SCHEMA_OBSERVED; historical coverage/lifecycle feasibility remains unresolved",
        "B2": "OPEN", "B3": "BLOCKED", "PRODUCT_READY": False,
        "review_limitations": ["Sanitized receipts reconcile recorded reservations, not provider invoice usage or direct private ledger database inspection.", "No provider calls, credentials, live follow-ups or acceptance calculations performed by this replay."]
    }
    (HERE / "REVIEW.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"state": receipt["state"], "verified_artifacts": len(checked_artifacts), "requests": 10, "conservative_credits": 73, "unique_indexed_records": 200, "failed_indexed_records": failed, "observed_seconds": max(times) - min(times), "B3": "BLOCKED", "receipt": str(HERE / "REVIEW.json")}))


if __name__ == "__main__":
    main()
