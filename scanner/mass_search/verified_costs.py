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


def classify_native_withdrawal(destination):
    meta = published_tip_lookup(destination)
    if meta:
        return "verified_tip"
    return "unresolved_debit"
