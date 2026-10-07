"""Local provider-call ledger. Ranked-100 product paths must stay at zero."""
from __future__ import annotations

from threading import Lock

PROVIDER_HOST_MARKERS = (
    "mainnet.helius-rpc.com",
    "public-api.birdeye.so",
    "api.mainnet-beta.solana.com",
    "api.devnet.solana.com",
    "api.jup.ag",
)

_LOCK = Lock()
_CALLS = []


def reset_provider_calls():
    with _LOCK:
        _CALLS.clear()


def record_provider_call(url, *, source="backend"):
    with _LOCK:
        _CALLS.append({"url": str(url), "source": source})


def provider_call_count():
    with _LOCK:
        return len(list(_CALLS))


def provider_calls():
    with _LOCK:
        return list(_CALLS)


def url_is_provider(url):
    text = str(url or "").lower()
    return any(marker in text for marker in PROVIDER_HOST_MARKERS)


def snapshot():
    return {
        "kind": "provider-call-ledger-v1",
        "backend_provider_calls": provider_call_count(),
        "calls": provider_calls(),
        "PRODUCT_READY": False,
    }
