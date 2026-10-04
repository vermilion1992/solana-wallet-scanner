"""Real-record arithmetic and deliberately incomplete certificate controls."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from scanner.evidence_audit import audit_raw_bundle, MAX_TRANSACTIONS
from scanner import evidence_audit
from scanner.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"
WALLET = "4drEkXDZhjun3vjZmz1g7pQGM7kxANQbDuD9jtPZwzJZ"
MINT = "GAwhcphCqCv5bKHmCiN4VDdNWfbXJL4npmkc8L3Q9S9H"
TOKEN_ACCOUNT = "47YKPtLHM5joKbW5hCFhXhZcigp4Xb9NrGpiKFjfsNUM"
WRAPPED_ACCOUNT = "8XeSQHdLxqhcFAegjUpYvaJu516GUPQttfPgen4eXFiG"
HASH = "9ffe9059c331907e4c8d9835e4c06fd1d258782da7b96c7bb639c00ded5001d0"


def bundle():
    return json.loads((FIXTURES / "real-transaction-audit-mainnet.json").read_text())


def rehash(value):
    for record in value["transactions"]:
        record["evidence_hash"] = sha256(json.dumps(record["raw"], sort_keys=True,
            ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()).hexdigest()
    return value


def alternate_signature(value):
    # Still a valid 64-byte base58 encoding, deliberately not the reviewed tx.
    return ("3" if value[0] != "3" else "2") + value[1:]


def test_real_mainnet_contract_has_exact_metrics_and_explicit_unknowns():
    expected = json.loads((FIXTURES / "real-transaction-audit-expected.json").read_text())
    result = audit_raw_bundle(bundle())
    assert result["source"] == "raw-mainnet-records"
    assert result["certificate"]["status"] == "SCOPED_RECONSTRUCTION"
    assert result["certificate"]["financial_qualification"] == "UNRESOLVED"
    assert result["certificate"]["wallet_history_complete"] is False
    assert result["scope"]["history_complete"] is False
    for key, value in expected["metrics"].items():
        assert result["metrics"][key]["value"] == value
        assert result["metrics"][key]["status"] == "known"
        assert result["metrics"][key]["evidence"] == [HASH]
    for key in expected["unknown_checks"]:
        assert result["certificate"]["checks"][key]["state"] == "UNKNOWN"
    for key in expected["unknown_metrics"]:
        assert result["metrics"][key]["value"] is None
        assert result["metrics"][key]["status"] == "unknown"
        assert result["metrics"][key]["reason"]
    row = result["reconstruction"][0]
    assert row["slot"] == expected["slot"]
    assert row["block_time"] == expected["block_time"]
    assert row["owned_balances"] == [{"account": TOKEN_ACCOUNT, "mint": MINT, "decimals": 6,
        "pre_quantity_raw": "44824210540", "post_quantity_raw": "55487822596",
        "delta_quantity_raw": "10663612056"}]
    assert row["native_equation"]["residual_lamports"] == "0"
    assert row["native_equation"]["expected_wallet_delta_lamports"] == "-253641389"
    assert row["wrap_lifecycle"] == [{"account": WRAPPED_ACCOUNT, "pre_lamports": "0", "post_lamports": "0",
        "rent_funded_lamports": "1488440", "rent_refunded_lamports": "1488440",
        "paths": ["innerInstructions.2.1", "innerInstructions.2.3", "instructions.7"]}]


def test_known_metric_dependencies_are_machine_checkable_and_reproducible():
    first, second = audit_raw_bundle(bundle()), audit_raw_bundle(bundle())
    assert first == second
    assert len(first["certificate"]["content_hash"]) == 64
    for metric in first["metrics"].values():
        if metric["status"] == "known":
            assert metric["required_checks"]
            assert all(first["certificate"]["checks"][key]["state"] == "PASS" for key in metric["required_checks"])
    changed = bundle()
    changed["scope"]["accounts"].remove(TOKEN_ACCOUNT)
    assert audit_raw_bundle(changed)["certificate"]["content_hash"] != first["certificate"]["content_hash"]


def test_archived_primary_raw_is_the_exact_hashed_record(tmp_path):
    store = Store(tmp_path)
    result = audit_raw_bundle(bundle(), store)
    assert store.evidence(HASH) == bundle()["transactions"][0]["raw"]
    assert result["evidence"] == [{"kind": "getTransaction", "signature": bundle()["scope"]["signatures"][0], "hash": HASH}]
    assert store.list("reservations") == []


@pytest.mark.parametrize("key", ["gross_buy_consideration_sol", "asset_net_quantities_raw", "native_wallet_delta_sol", "wallet_network_fees_sol"])
def test_raw_tampering_with_an_old_hash_revokes_dependent_metrics(key):
    value = bundle()
    value["transactions"][0]["raw"]["meta"]["fee"] += 1
    result = audit_raw_bundle(value)
    assert result["certificate"]["checks"]["raw_integrity"]["state"] == "FAIL"
    assert result["certificate"]["status"] == "INCOMPLETE"
    assert result["metrics"][key]["value"] is None
    assert result["source"] == "unverified-import"


@pytest.mark.parametrize("digest", ["fake-mainnet-hash", "A" * 64, "0" * 64, 42])
def test_invalid_or_mismatching_hash_is_never_trusted(digest):
    value = bundle()
    value["transactions"][0]["evidence_hash"] = digest
    assert audit_raw_bundle(value)["certificate"]["checks"]["raw_integrity"]["state"] == "FAIL"


def test_recomputed_modified_import_has_no_mainnet_provenance_or_classification():
    value = bundle()
    raw = value["transactions"][0]["raw"]
    # RPC uiAmount is never an accounting input; exact integers remain intact.
    raw["meta"]["preTokenBalances"][0]["uiTokenAmount"]["uiAmount"] = 999.125
    value.update(source="mainnet", history_complete=True, evidence_verified=True,
                 classification="meme", certificate={"wallet_history_complete": True})
    value["transactions"][0]["classification"] = "meme"
    result = audit_raw_bundle(rehash(value))
    assert result["source"] == "unverified-import"
    assert result["certificate"]["checks"]["chain_provenance"]["state"] == "UNKNOWN"
    assert result["metrics"]["gross_buy_consideration_sol"]["value"] == "0.25"
    assert result["certificate"]["checks"]["classification"]["state"] == "UNKNOWN"
    assert all(event.get("classification", "unknown") == "unknown" for event in result["events"])
    assert result["certificate"]["wallet_history_complete"] is False


def test_missing_claimed_record_fails_set_coverage_without_zero_fill():
    value = bundle()
    value["scope"]["signatures"].append(alternate_signature(value["scope"]["signatures"][0]))
    result = audit_raw_bundle(value)
    assert result["certificate"]["checks"]["transaction_set"]["state"] == "FAIL"
    assert all(metric["value"] is None for metric in result["metrics"].values())
    # Exact single-record observations remain visible for independent inspection.
    assert result["reconstruction"][0]["checks"]["swap_quantity"]["state"] == "PASS"


@pytest.mark.parametrize("duplicate", ["record", "claimed-signature"])
def test_duplicate_record_or_claimed_signature_fails_coverage(duplicate):
    value = bundle()
    if duplicate == "record":
        value["transactions"].append(deepcopy(value["transactions"][0]))
    else:
        value["scope"]["signatures"].append(value["scope"]["signatures"][0])
    result = audit_raw_bundle(value)
    assert result["certificate"]["checks"]["transaction_set"]["state"] == "FAIL"
    assert result["metrics"]["gross_buy_consideration_sol"]["value"] is None


@pytest.mark.parametrize("account", [WALLET, TOKEN_ACCOUNT, WRAPPED_ACCOUNT])
def test_missing_involved_owned_account_revokes_scoped_trade_metrics(account):
    value = bundle()
    value["scope"]["accounts"].remove(account)
    result = audit_raw_bundle(value)
    assert result["certificate"]["checks"]["account_boundary"]["state"] == "FAIL"
    assert account in result["certificate"]["checks"]["account_boundary"]["actual"]["missing"]
    assert result["metrics"]["asset_net_quantities_raw"]["value"] is None
    assert result["metrics"]["gross_buy_consideration_sol"]["value"] is None
    # The raw wallet fee does not depend on token account enumeration.
    assert result["metrics"]["wallet_network_fees_sol"]["value"] == "0.000141389"


def test_extra_unproven_account_is_unknown_and_inferred_scope_never_means_wallet_scope():
    value = bundle()
    value["scope"]["accounts"].append("11111111111111111111111111111111")
    result = audit_raw_bundle(value)
    assert result["certificate"]["checks"]["account_boundary"]["state"] == "UNKNOWN"
    assert result["metrics"]["gross_buy_consideration_sol"]["value"] is None
    value["scope"].pop("accounts")
    result = audit_raw_bundle(value)
    assert result["certificate"]["checks"]["account_boundary"]["state"] == "PASS"
    assert set(result["scope"]["accounts"]) == {WALLET, TOKEN_ACCOUNT, WRAPPED_ACCOUNT}
    assert result["certificate"]["checks"]["wallet_history"]["state"] == "UNKNOWN"


@pytest.mark.parametrize("component", ["create", "initialize", "close", "sync", "funding"])
def test_missing_real_wrapped_sol_primary_path_revokes_trade(component):
    value = bundle()
    raw = value["transactions"][0]["raw"]
    if component in ("create", "initialize"):
        group = next(group for group in raw["meta"]["innerInstructions"] if group["index"] == 2)
        kind = "createAccount" if component == "create" else "initializeAccount3"
        group["instructions"] = [instruction for instruction in group["instructions"] if instruction.get("parsed", {}).get("type") != kind]
    else:
        index = {"close": 7, "sync": 5, "funding": 4}[component]
        # Preserve outer indices and route identity; remove the meaningful raw
        # step by replacing it with a reviewed zero-effect compute instruction.
        raw["transaction"]["message"]["instructions"][index] = deepcopy(raw["transaction"]["message"]["instructions"][0])
    result = audit_raw_bundle(rehash(value))
    assert result["certificate"]["status"] == "INCOMPLETE"
    assert result["metrics"]["gross_buy_consideration_sol"]["value"] is None
    assert result["metrics"]["asset_net_quantities_raw"]["value"] is None


@pytest.mark.parametrize("component", ["fee", "post-token", "both-token", "token-cpi", "native-unit", "unsupported-program", "signer"])
def test_primary_raw_omissions_or_disagreements_fail_affected_checks(component):
    value = bundle()
    raw = value["transactions"][0]["raw"]
    if component == "fee":
        raw["meta"].pop("fee")
    elif component in ("post-token", "both-token"):
        raw["meta"]["postTokenBalances"] = [row for row in raw["meta"]["postTokenBalances"] if row["accountIndex"] != 2]
        if component == "both-token":
            raw["meta"]["preTokenBalances"] = [row for row in raw["meta"]["preTokenBalances"] if row["accountIndex"] != 2]
    elif component == "token-cpi":
        group = next(group for group in raw["meta"]["innerInstructions"] if group["index"] == 6)
        group["instructions"].pop(1)
    elif component == "native-unit":
        raw["meta"]["postBalances"][0] += 1
    elif component == "unsupported-program":
        raw["transaction"]["message"]["instructions"][6]["programId"] = "11111111111111111111111111111111"
    else:
        raw["transaction"]["message"]["accountKeys"][0]["signer"] = False
    result = audit_raw_bundle(rehash(value))
    assert result["certificate"]["status"] == "INCOMPLETE"
    assert result["metrics"]["gross_buy_consideration_sol"]["value"] is None
    assert result["metrics"]["asset_net_quantities_raw"]["value"] is None
    if component == "fee":
        assert result["metrics"]["wallet_network_fees_sol"]["value"] is None


def test_existing_unknown_receipts_are_not_zero_cost_opening_inventory():
    value = bundle()
    result = audit_raw_bundle(value)
    assert result["reconstruction"][0]["owned_balances"][0]["pre_quantity_raw"] == "44824210540"
    assert result["metrics"]["opening_basis_sol"]["value"] is None
    assert result["metrics"]["wallet_profit_sol"]["value"] is None
    # Even a changed imported zero endpoint cannot prove no other owned account.
    raw = value["transactions"][0]["raw"]
    for row in raw["meta"]["preTokenBalances"]:
        if row["owner"] == WALLET:
            row["uiTokenAmount"]["amount"] = "0"
    for row in raw["meta"]["postTokenBalances"]:
        if row["owner"] == WALLET:
            row["uiTokenAmount"]["amount"] = "10663612056"
    result = audit_raw_bundle(rehash(value))
    assert result["metrics"]["gross_buy_consideration_sol"]["value"] == "0.25"
    assert result["certificate"]["checks"]["opening_basis"]["state"] == "UNKNOWN"
    assert result["certificate"]["checks"]["wallet_history"]["state"] == "UNKNOWN"


@pytest.mark.parametrize("component", ["version", "address", "scope-kind", "records-limit", "scope-signature", "record-signature", "nan"])
def test_invalid_imports_are_rejected_before_certificate_claims(component):
    value = bundle()
    if component == "version":
        value["version"] = "financial-certification-v99"
    elif component == "address":
        value["address"] = "not-a-wallet"
    elif component == "scope-kind":
        value["scope"]["kind"] = "all-wallet-history"
    elif component == "records-limit":
        value["transactions"] *= MAX_TRANSACTIONS + 1
    elif component == "scope-signature":
        value["scope"]["signatures"][0] = "synthetic-signature"
    elif component == "record-signature":
        value["transactions"][0]["signature"] = {"claim": "mainnet"}
    else:
        value["transactions"][0]["raw"]["meta"]["fee"] = float("nan")
    with pytest.raises(ValueError):
        audit_raw_bundle(value)


def test_missing_raw_is_a_failed_claim_and_does_not_disappear():
    value = bundle()
    value["transactions"][0].pop("raw")
    result = audit_raw_bundle(value)
    assert result["certificate"]["checks"]["raw_integrity"]["state"] == "FAIL"
    assert result["certificate"]["status"] == "INCOMPLETE"
    assert result["metrics"]["transaction_count"]["value"] is None
    assert result["reconstruction"][0]["signature"] == value["scope"]["signatures"][0]


def test_rpc_envelope_unwrap_preserves_canonical_primary_hash():
    value = bundle()
    record = value["transactions"][0]
    record["raw"] = {"jsonrpc": "2.0", "id": 1, "result": record["raw"]}
    result = audit_raw_bundle(value)
    assert result["source"] == "raw-mainnet-records"
    assert result["evidence"][0]["hash"] == HASH


def test_full_known_record_set_never_uses_supplied_financial_booleans():
    value = bundle()
    value["scope"].update(history_complete=True, historical_ownership_verified=True,
                          acquired_basis_complete=True, meme_classification_verified=True)
    value.update(metrics={"wallet_profit_sol": "999"}, policy="MATCH")
    result = audit_raw_bundle(value)
    assert result["certificate"]["financial_qualification"] == "UNRESOLVED"
    assert result["metrics"]["wallet_profit_sol"]["status"] == "unknown"
    assert result["certificate"]["wallet_history_complete"] is False


@pytest.mark.parametrize("component", ["program", "space", "rent", "sync"])
def test_invalid_temporary_lifecycle_never_claims_a_known_refund(component):
    value = bundle()
    raw = value["transactions"][0]["raw"]
    group = next(group for group in raw["meta"]["innerInstructions"] if group["index"] == 2)
    create = next(instruction for instruction in group["instructions"] if instruction.get("parsed", {}).get("type") == "createAccount")
    if component == "program":
        create["parsed"]["info"]["owner"] = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
    elif component == "space":
        create["parsed"]["info"]["space"] = 164
    elif component == "rent":
        create["parsed"]["info"]["lamports"] = 0
    else:
        raw["transaction"]["message"]["instructions"][5] = deepcopy(raw["transaction"]["message"]["instructions"][0])
    result = audit_raw_bundle(rehash(value))
    assert result["certificate"]["checks"]["wrap_lifecycle"]["state"] != "PASS"
    assert result["certificate"]["checks"]["account_ownership"]["state"] != "PASS"
    assert result["reconstruction"][0]["wrap_lifecycle"] == []
    assert result["metrics"]["gross_buy_consideration_sol"]["value"] is None


@pytest.mark.parametrize("component", ["unsupported", "changed"])
def test_supplied_token_program_identity_cannot_be_ignored(component):
    value = bundle()
    raw = value["transactions"][0]["raw"]
    owned_post = next(row for row in raw["meta"]["postTokenBalances"] if row["owner"] == WALLET)
    owned_post["programId"] = "11111111111111111111111111111111" if component == "unsupported" else "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    result = audit_raw_bundle(rehash(value))
    assert result["certificate"]["checks"]["account_ownership"]["state"] == "FAIL"
    assert result["metrics"]["asset_net_quantities_raw"]["value"] is None


def test_failed_raw_instructions_do_not_prove_committed_wrapping_or_purchase():
    value = bundle()
    raw = value["transactions"][0]["raw"]
    raw["meta"]["err"] = {"InstructionError": [6, "Custom"]}
    raw["meta"]["postBalances"] = raw["meta"]["preBalances"].copy()
    raw["meta"]["postBalances"][0] -= raw["meta"]["fee"]
    raw["meta"]["postTokenBalances"] = deepcopy(raw["meta"]["preTokenBalances"])
    result = audit_raw_bundle(rehash(value))
    assert result["certificate"]["checks"]["network_fees"]["state"] == "PASS"
    assert result["certificate"]["checks"]["native_reconciliation"]["state"] == "PASS"
    assert result["certificate"]["checks"]["wrap_lifecycle"]["state"] == "UNKNOWN"
    assert result["reconstruction"][0]["wrap_lifecycle"] == []
    assert result["metrics"]["wallet_network_fees_sol"]["value"] == "0.000141389"
    assert result["metrics"]["native_wallet_delta_sol"]["value"] == "-0.000141389"
    assert result["metrics"]["gross_buy_consideration_sol"]["value"] is None
    assert [event["kind"] for event in result["events"]] == ["fee"]
    assert result["certificate"]["checks"]["fee_allocation"]["state"] == "PASS"


def test_fee_claim_that_disagrees_with_native_records_is_unknown_as_a_metric():
    value = bundle()
    value["transactions"][0]["raw"]["meta"]["fee"] += 1
    result = audit_raw_bundle(rehash(value))
    assert result["certificate"]["checks"]["network_fees"]["state"] == "FAIL"
    assert result["metrics"]["wallet_network_fees_sol"]["value"] is None
    assert result["metrics"]["gross_buy_consideration_sol"]["value"] is None


def test_wrapper_signature_does_not_substitute_for_native_record_identity():
    value = bundle()
    claimed = alternate_signature(value["scope"]["signatures"][0])
    value["scope"]["signatures"] = [claimed]
    value["transactions"][0]["signature"] = claimed
    result = audit_raw_bundle(value)
    assert result["certificate"]["checks"]["transaction_set"]["state"] == "FAIL"
    assert result["metrics"]["transaction_count"]["value"] is None
    assert result["source"] == "unverified-import"


def test_excessive_json_nesting_is_a_controlled_invalid_import():
    value = bundle()
    nested = {}
    value["nested"] = nested
    for _ in range(1100):
        nested["child"] = {}
        nested = nested["child"]
    with pytest.raises(ValueError, match="nesting"):
        audit_raw_bundle(value)


@pytest.mark.parametrize("component", ["native-balance", "network-fee", "slot", "token-balance", "token-transfer", "native-transfer"])
def test_impossible_protocol_integers_cannot_become_known_rounded_metrics(component):
    value = bundle()
    raw = value["transactions"][0]["raw"]
    if component == "native-balance":
        raw["meta"]["preBalances"][0] = 2**64
    elif component == "network-fee":
        raw["meta"]["fee"] = 2**64
    elif component == "slot":
        raw["slot"] = 2**64
    elif component == "token-balance":
        raw["meta"]["preTokenBalances"][0]["uiTokenAmount"]["amount"] = str(2**64)
    elif component == "token-transfer":
        group = next(group for group in raw["meta"]["innerInstructions"] if group["index"] == 6)
        transfer = next(instruction for instruction in group["instructions"] if instruction.get("parsed", {}).get("type") == "transferChecked")
        transfer["parsed"]["info"]["tokenAmount"]["amount"] = str(2**64)
    else:
        raw["transaction"]["message"]["instructions"][8]["parsed"]["info"]["lamports"] = 2**64
    result = audit_raw_bundle(rehash(value))
    assert result["certificate"]["status"] == "INCOMPLETE"
    assert result["metrics"]["gross_buy_consideration_sol"]["value"] is None
    assert result["metrics"]["asset_net_quantities_raw"]["value"] is None
    if component in ("network-fee", "slot"):
        assert result["metrics"]["wallet_network_fees_sol"]["value"] is None


def no_outside_movements():
    """Synthetic raw control retaining the supported route, not a chain claim."""
    value = bundle()
    raw = value["transactions"][0]["raw"]
    keys = [entry["pubkey"] for entry in raw["transaction"]["message"]["accountKeys"]]
    instructions = raw["transaction"]["message"]["instructions"]
    for index in (8, 9):
        info = instructions[index]["parsed"]["info"]
        raw["meta"]["postBalances"][keys.index(info["destination"])] -= info["lamports"]
        raw["meta"]["postBalances"][keys.index(info["source"])] += info["lamports"]
        # Keep unrelated raw instruction indices stable.
        instructions[index] = deepcopy(instructions[0])
    return rehash(value)


def offsetting_unknown_movements():
    """The independent R5 shape: unknown withdrawals and equal signed inflow."""
    value = bundle()
    raw = value["transactions"][0]["raw"]
    message, meta = raw["transaction"]["message"], raw["meta"]
    donor = message["instructions"][8]["parsed"]["info"]["destination"]
    old_keys = message["accountKeys"]
    donor_index = next(index for index, key in enumerate(old_keys) if key["pubkey"] == donor)
    # The incoming donor is a declared second signer. This mutation does not
    # assert valid cryptographic signatures or actual mainnet execution.
    order = [0, donor_index] + [index for index in range(1, len(old_keys)) if index != donor_index]
    remap = {old: new for new, old in enumerate(order)}
    message["accountKeys"] = [old_keys[index] for index in order]
    message["accountKeys"][1]["signer"] = True
    raw["transaction"]["signatures"].append("1" * 64)
    for name in ("preBalances", "postBalances"):
        meta[name] = [meta[name][index] for index in order]
    for name in ("preTokenBalances", "postTokenBalances"):
        for row in meta[name]:
            row["accountIndex"] = remap[row["accountIndex"]]
    message["instructions"].append({"program": "system", "programId": "11111111111111111111111111111111",
        "parsed": {"type": "transfer", "info": {"source": donor, "destination": value["address"], "lamports": 3500000}}, "stackHeight": 1})
    meta["postBalances"][0] += 3500000 - 5000
    meta["postBalances"][1] -= 3500000
    meta["fee"] += 5000
    return rehash(value)


@pytest.mark.parametrize("offset", [False, True])
def test_individual_unknown_movements_prevent_fee_completion_regardless_of_net(offset):
    value = offsetting_unknown_movements() if offset else bundle()
    result = audit_raw_bundle(value)
    capital = [event for event in result["events"] if event["kind"] == "capital"]
    assert len(capital) == (3 if offset else 2)
    assert all(event["economic_role"] == "unknown" for event in capital)
    assert result["certificate"]["checks"]["native_reconciliation"]["state"] == "PASS"
    assert result["metrics"]["outside_native_delta_sol"]["value"] == ("0" if offset else "-0.0035")
    assert result["certificate"]["checks"]["fee_allocation"]["state"] == "UNKNOWN"
    fee = next(event for event in result["events"] if event["kind"] == "fee")
    assert fee["allocation"] == "unallocated"
    assert result["metrics"]["wallet_profit_sol"]["value"] is None
    assert result["certificate"]["financial_qualification"] == "UNRESOLVED"
    if offset:
        assert result["source"] == "unverified-import"
    individual = result["reconstruction"][0]["checks"]["fee_allocation"]["actual"]["outside_movements"]
    assert len(individual) == len(capital)


def test_no_outside_flows_certify_the_actual_exact_buy_fee_link():
    result = audit_raw_bundle(no_outside_movements())
    assert result["version"] == "scoped-evidence-audit-v2"
    assert result["source"] == "unverified-import"
    assert result["certificate"]["checks"]["native_reconciliation"]["state"] == "PASS"
    assert result["certificate"]["checks"]["fee_allocation"]["state"] == "PASS"
    fee = next(event for event in result["events"] if event["kind"] == "fee")
    trade = next(event for event in result["events"] if event["kind"] == "buy")
    assert fee["allocation"] == "buy_basis"
    assert fee["allocated_trade_path"] == trade["path"]
    assert fee["amount_sol"] == trade["fee_sol"] == "0.000141389"
    assert not any(event["kind"] == "capital" for event in result["events"])
    assert result["metrics"]["wallet_profit_sol"]["value"] is None


@pytest.mark.parametrize("damage,expected", [("missing-link", "UNKNOWN"), ("wrong-path", "FAIL"),
    ("wrong-fee", "FAIL"), ("duplicate", "UNKNOWN"), ("missing-fee", "UNKNOWN")])
def test_fee_completion_requires_valid_actual_decoder_records(monkeypatch, damage, expected):
    original = evidence_audit.decode_supported_swaps

    def damaged_decoder(*args, **kwargs):
        decoded = original(*args, **kwargs)
        fee = next(event for event in decoded["events"] if event["kind"] == "fee")
        if damage == "missing-link":
            fee["allocation"] = "unallocated"
            fee.pop("allocated_trade_path", None)
        elif damage == "wrong-path":
            fee["allocated_trade_path"] = "instructions.not-this-trade"
        elif damage == "wrong-fee":
            fee["amount_sol"] = "0.000141390"
        elif damage == "duplicate":
            decoded["events"].append(deepcopy(fee))
        else:
            decoded["events"] = [event for event in decoded["events"] if event["kind"] != "fee"]
        return decoded

    monkeypatch.setattr(evidence_audit, "decode_supported_swaps", damaged_decoder)
    result = audit_raw_bundle(no_outside_movements())
    assert result["certificate"]["checks"]["native_reconciliation"]["state"] == "PASS"
    assert result["certificate"]["checks"]["fee_allocation"]["state"] == expected
    assert result["metrics"]["wallet_network_fees_sol"]["value"] == "0.000141389"
    assert result["metrics"]["wallet_profit_sol"]["value"] is None


def test_failed_overhead_cannot_pass_when_native_fee_charging_disagrees():
    value = bundle()
    raw = value["transactions"][0]["raw"]
    raw["meta"]["err"] = {"InstructionError": [6, "Custom"]}
    raw["meta"]["postBalances"] = raw["meta"]["preBalances"].copy()
    raw["meta"]["postBalances"][0] -= raw["meta"]["fee"] + 1
    result = audit_raw_bundle(rehash(value))
    assert result["certificate"]["checks"]["native_reconciliation"]["state"] == "FAIL"
    assert result["certificate"]["checks"]["fee_allocation"]["state"] == "FAIL"
    assert result["metrics"]["wallet_network_fees_sol"]["value"] is None


def test_sponsored_fee_exclusion_uses_native_payer_and_actual_decoder_records():
    value = no_outside_movements()
    raw = value["transactions"][0]["raw"]
    message, meta = raw["transaction"]["message"], raw["meta"]
    sponsor = bundle()["transactions"][0]["raw"]["transaction"]["message"]["instructions"][8]["parsed"]["info"]["destination"]
    old_keys = message["accountKeys"]
    sponsor_index = next(index for index, key in enumerate(old_keys) if key["pubkey"] == sponsor)
    order = [sponsor_index, 0] + [index for index in range(1, len(old_keys)) if index != sponsor_index]
    remap = {old: new for new, old in enumerate(order)}
    message["accountKeys"] = [old_keys[index] for index in order]
    message["accountKeys"][0]["signer"] = True
    raw["transaction"]["signatures"].append("1" * 64)
    for name in ("preBalances", "postBalances"):
        meta[name] = [meta[name][index] for index in order]
    for name in ("preTokenBalances", "postTokenBalances"):
        for row in meta[name]:
            row["accountIndex"] = remap[row["accountIndex"]]
    # The signer metadata and relocated debit are a synthetic payer control.
    meta["postBalances"][0] -= meta["fee"]
    meta["postBalances"][1] += meta["fee"]
    result = audit_raw_bundle(rehash(value))
    assert result["certificate"]["checks"]["native_reconciliation"]["state"] == "PASS"
    assert result["certificate"]["checks"]["fee_allocation"]["state"] == "PASS"
    assert result["metrics"]["wallet_network_fees_sol"]["value"] == "0"
    fee = next(event for event in result["events"] if event["kind"] == "fee")
    trade = next(event for event in result["events"] if event["kind"] == "buy")
    assert fee["paid_by_wallet"] is False and fee["allocation"] == "unallocated"
    assert trade["fee_sol"] == "0"
