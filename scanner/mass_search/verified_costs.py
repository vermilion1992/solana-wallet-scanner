"""Documented tip and priority-fee recipients. Arbitrary SOL withdrawals are not tips."""
from __future__ import annotations

import json
from pathlib import Path

PINNED_TIP_ACCOUNTS_PATH = Path(__file__).with_name("published_tip_accounts.json")


def _load_published():
    payload = json.loads(PINNED_TIP_ACCOUNTS_PATH.read_text(encoding="utf-8"))
    accounts = {}
    programs = set()
    sources = {}
    for provider, body in (payload.get("providers") or {}).items():
        source = body.get("source")
        sources[provider] = source
        for address in body.get("accounts") or []:
            accounts[address] = {"provider": provider, "source": source}
        for address in body.get("programs") or []:
            programs.add(address)
            accounts[address] = {"provider": provider, "source": source, "kind": "program"}
    return {
        "accounts": accounts,
        "programs": frozenset(programs),
        "sources": sources,
        "payload": payload,
    }


_PUBLISHED = _load_published()
PUBLISHED_TIP_ACCOUNTS = frozenset(_PUBLISHED["accounts"])
JITO_TIP_ACCOUNTS = frozenset(
    address
    for address, meta in _PUBLISHED["accounts"].items()
    if meta.get("provider") == "jito" and meta.get("kind") != "program"
)
JITO_TIP_PROGRAM = "T1pyyaTNZsKv2WcRAB8oVnk93mLBw6NYZb1hEz6G5Vu"


def published_tip_lookup(address):
    return _PUBLISHED["accounts"].get(address)


def is_verified_tip_account(address):
    return address in PUBLISHED_TIP_ACCOUNTS


# Proven router/platform fee recipients. These are costs even when the
# destination is not on a published tip list. Unexplained transfers stay
# sensitivity and are never called fees.
DOCUMENTED_PLATFORM_FEE_ACCOUNTS = {
    # Jupiter aggregator platform-fee / referral vaults cited in official IDL
    # layouts. RFQ 9PnYDC… is attributed only by the exact fee-fill pattern
    # in Phase 2 — listing it here would weaken the unrelated-transfer guard.
}


def is_proven_router_or_platform_fee(destination, *, proven_from_layout=False):
    if proven_from_layout:
        return True
    return destination in DOCUMENTED_PLATFORM_FEE_ACCOUNTS


def classify_cost_role(destination, *, proven_from_layout=False, transaction_failed=False,
                       wallet_paid_network=False, transfer=False):
    """Classify a debit. Unexplained transfers are never called fees."""
    if wallet_paid_network and not transfer:
        return "network_plus_priority_fee"
    if transaction_failed and transfer:
        return "failed_tx_transfer_excluded"
    if is_verified_tip_account(destination):
        return "verified_tip"
    if is_proven_router_or_platform_fee(destination, proven_from_layout=proven_from_layout):
        return "proven_router_or_platform_fee"
    return "unexplained_transfer"


def classify_native_withdrawal(destination, *, proven_from_layout=False):
    role = classify_cost_role(destination, proven_from_layout=proven_from_layout, transfer=True)
    if role == "verified_tip":
        return "verified_tip"
    if role == "proven_router_or_platform_fee":
        return "proven_router_or_platform_fee"
    return "unresolved_debit"
