"""Separate credentials from economic transaction evidence.

Substring redaction of api[_-]?key|authorization|secret|token|password|credential
destroyed preTokenBalances, uiTokenAmount, tokenAmount and public SPL Token
program IDs. This module is schema-aware: real secrets stay protected; public
token fields and program IDs are preserved. Integrity failure is not an
unsupported trade.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy

from .plan import canonical_json

REDACTED = "[REDACTED]"
SOURCE_RECORDS_DAMAGED = "SOURCE_RECORDS_DAMAGED"
SOURCE_RECORDS_INTACT = "SOURCE_RECORDS_INTACT"
PAGE_KIND_V1 = "g3-history-page-v1"
PAGE_KIND_V2 = "g3-history-page-v2"
CACHE_KEY_PREFIX_V1 = "g3-history:"
CACHE_KEY_PREFIX_V2 = "g3-history-v2:"

CREDENTIAL_KEY_RE = re.compile(
    r"^(?:x-)?(?:api[_-]?key|authorization|password|secret|credential|bearer)$",
    re.I,
)
SECRET_QUERY_RE = re.compile(
    r"(?i)(?:api[_-]?key|access_token|secret|authorization)=([^&\s\"']+)"
)
SECRET_ENV_NAMES = (
    "BIRDEYE_API_KEY",
    "HELIUS_API_KEY",
    "HELIUS_KEY",
    "HELIUS_API_KEYS",
)
PRESERVED_KEYS = frozenset({
    "preTokenBalances",
    "postTokenBalances",
    "preBalances",
    "postBalances",
    "uiTokenAmount",
    "tokenAmount",
    "tokenAccounts",
    "tokenAccount",
    "programId",
    "program",
    "accountKeys",
    "authorization_id",
    "authorized_by_user_at",
    "authorized_by_user_at_local",
})
PUBLIC_PROGRAM_IDS = frozenset({
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "11111111111111111111111111111111",
    "ComputeBudget111111111111111111111111111111",
})
PUBLIC_PROGRAM_NAMES = frozenset({
    "spl-token",
    "spl-token-2022",
    "system",
    "spl-associated-token-account",
})
REQUIRED_BALANCE_FIELDS = ("preTokenBalances", "postTokenBalances")


def is_credential_key(key):
    text = str(key)
    if text in PRESERVED_KEYS:
        return False
    return bool(CREDENTIAL_KEY_RE.match(text))


def is_public_program_value(value):
    if not isinstance(value, str):
        return False
    if value in PUBLIC_PROGRAM_IDS or value in PUBLIC_PROGRAM_NAMES:
        return True
    return value.startswith("Tokenkeg") or value.startswith("TokenzQd")


def secret_env_values():
    values = []
    for name in SECRET_ENV_NAMES:
        raw = os.environ.get(name)
        if not raw:
            continue
        parts = [raw]
        if "," in raw:
            parts.extend(item.strip() for item in raw.split(","))
        for item in parts:
            if item and len(item) >= 8:
                values.append(item)
    return values


def is_secret_string(value):
    if not isinstance(value, str) or len(value) < 8:
        return False
    if is_public_program_value(value):
        return False
    if SECRET_QUERY_RE.search(value):
        return True
    return any(secret in value for secret in secret_env_values())


def redact_text(value):
    """Scrub secrets from any string that will be logged, printed, or saved."""
    if value is None:
        return value
    if not isinstance(value, str):
        try:
            text = str(value)
        except Exception:
            return "[REDACTED]"
    else:
        text = value
    text = SECRET_QUERY_RE.sub(
        lambda match: match.group(0).split("=", 1)[0] + "=" + REDACTED, text
    )
    for secret in secret_env_values():
        if secret and secret in text:
            text = text.replace(secret, REDACTED)
    return text


def redact_secrets(value):
    """Protect credential fields and authenticated URLs. Preserve public token data."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if is_credential_key(key):
                cleaned[key] = REDACTED
            else:
                cleaned[key] = redact_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def scrub_bytes(data, extra_secrets=None):
    """Redact secrets in raw bytes. Returns (written_bytes, original_sha256, scrubbed)."""
    raw = data if isinstance(data, (bytes, bytearray)) else bytes(data)
    original = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
        encoding = "latin-1"
    redacted = redact_text(text)
    for secret in extra_secrets or ():
        if secret and len(str(secret)) >= 8 and str(secret) in redacted:
            redacted = redacted.replace(str(secret), REDACTED)
    if redacted == text:
        return bytes(raw), original, False
    written = redacted.encode(encoding)
    return written, original, True


def _hash_payload(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def validate_transaction_record(record):
    """Fail closed when required balances were destroyed or the envelope is unusable."""
    if not isinstance(record, dict):
        return {"ok": False, "code": "MALFORMED", "detail": "record_not_object"}
    meta = record.get("meta")
    if meta == REDACTED or isinstance(meta, str):
        return {"ok": False, "code": SOURCE_RECORDS_DAMAGED, "detail": "meta_redacted_or_non_object"}
    if not isinstance(meta, dict):
        return {"ok": False, "code": "MALFORMED", "detail": "missing_meta"}
    for field in REQUIRED_BALANCE_FIELDS:
        value = meta.get(field)
        if value == REDACTED or isinstance(value, str):
            return {"ok": False, "code": SOURCE_RECORDS_DAMAGED, "detail": f"{field}_destroyed"}
        if value is not None and not isinstance(value, list):
            return {"ok": False, "code": SOURCE_RECORDS_DAMAGED, "detail": f"{field}_not_array"}
        if isinstance(value, list):
            for row in value:
                if not isinstance(row, dict):
                    return {"ok": False, "code": SOURCE_RECORDS_DAMAGED, "detail": f"{field}_row_not_object"}
                amount = row.get("uiTokenAmount")
                if amount == REDACTED or isinstance(amount, str):
                    return {"ok": False, "code": SOURCE_RECORDS_DAMAGED, "detail": "uiTokenAmount_destroyed"}
    return {"ok": True, "code": SOURCE_RECORDS_INTACT, "detail": None}


def classify_records(records):
    """Count damaged vs malformed vs intact. Do not treat damage as unsupported trading."""
    if not isinstance(records, list):
        return {
            "status": "MALFORMED",
            "records": 0,
            "intact": 0,
            "damaged": 0,
            "malformed": 0,
            "integrity_failure": True,
            "all_unsupported": False,
        }
    intact = damaged = malformed = 0
    for record in records:
        checked = validate_transaction_record(record)
        if checked["code"] == SOURCE_RECORDS_DAMAGED:
            damaged += 1
        elif not checked["ok"]:
            malformed += 1
        else:
            intact += 1
    if damaged:
        status = SOURCE_RECORDS_DAMAGED
    elif malformed and not intact:
        status = "MALFORMED"
    elif not records:
        status = "EMPTY"
    else:
        status = SOURCE_RECORDS_INTACT
    return {
        "status": status,
        "records": len(records),
        "intact": intact,
        "damaged": damaged,
        "malformed": malformed,
        "integrity_failure": damaged > 0,
        "all_unsupported": False,
    }


def classify_decoded_sample(decoded, integrity):
    """Classify an intact sample. Integrity failures stay distinct from venue gaps."""
    if integrity.get("integrity_failure") or integrity.get("status") == SOURCE_RECORDS_DAMAGED:
        return {
            "classification": SOURCE_RECORDS_DAMAGED,
            "justifies_further_page": False,
            "reason": "corrupted_inputs_do_not_justify_another_page",
        }
    if integrity.get("status") == "MALFORMED":
        return {
            "classification": "MALFORMED",
            "justifies_further_page": False,
            "reason": "malformed_inputs_do_not_justify_another_page",
        }
    events = list((decoded or {}).get("events") or [])
    coverage = (decoded or {}).get("coverage") or {}
    buys_sells = [row for row in events if row.get("kind") in ("buy", "sell")]
    unresolved = list((decoded or {}).get("unresolved") or [])
    reasons = " ".join(str(row.get("reason") or "") for row in unresolved)
    if not events and not coverage.get("transactions"):
        return {
            "classification": "INACTIVITY",
            "justifies_further_page": False,
            "reason": "empty_sample",
        }
    if not buys_sells:
        if "No reviewed outer spot swap" in reasons or "transfers and balances alone" in reasons:
            return {
                "classification": "TRANSFERS_WITHOUT_REVIEWED_SWAP",
                "justifies_further_page": False,
                "reason": "unsupported_semantics_do_not_justify_another_page",
            }
        if coverage.get("decoded_swaps") == 0:
            return {
                "classification": "UNSUPPORTED",
                "justifies_further_page": False,
                "reason": "unsupported_semantics_do_not_justify_another_page",
            }
        return {
            "classification": "INSUFFICIENT_SAMPLE",
            "justifies_further_page": True,
            "reason": "insufficient_sample",
        }
    kinds = {row.get("kind") for row in buys_sells}
    if "sell" in kinds and "buy" not in kinds:
        return {
            "classification": "MISSING_ACQUISITION",
            "justifies_further_page": True,
            "reason": "missing_acquisition_may_need_earlier_page",
        }
    return {
        "classification": "SUPPORTED_ACTIVITY",
        "justifies_further_page": True,
        "reason": "insufficient_episodes_on_intact_sample",
    }


def sanitize_transaction_records(records):
    """Versioned sanitize: credentials out, public token fields in, hashes distinct."""
    if not isinstance(records, list):
        records = []
    source = redact_secrets(deepcopy(records))
    integrity = classify_records(source)
    return {
        "records": source,
        "integrity": integrity,
        "source_body_sha256": _hash_payload(source),
        "normalized_sha256": _hash_payload({"kind": PAGE_KIND_V2, "records": source}),
    }


def sanitize_jsonrpc_body(body):
    """Strip credential metadata from a JSON-RPC envelope without destroying result.data."""
    return redact_secrets(deepcopy(body))


def legacy_substring_redact(value):
    """Exact reviewed defect at 864a75b. Kept only to prove the old collision."""
    blocked = re.compile(r"(api[_-]?key|authorization|secret|token|password|credential)", re.I)
    if isinstance(value, dict):
        return {key: REDACTED if blocked.search(str(key)) else legacy_substring_redact(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [legacy_substring_redact(item) for item in value]
    if isinstance(value, str) and len(value) >= 8 and blocked.search(value):
        return REDACTED
    return value


def structural_redaction_fixture():
    token_program = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    return {
        "transaction": {
            "message": {"accountKeys": [token_program], "instructions": []},
        },
        "meta": {
            "err": None,
            "preTokenBalances": [
                {"accountIndex": 0, "uiTokenAmount": {"amount": "10", "decimals": 6}},
            ],
            "postTokenBalances": [
                {"accountIndex": 0, "uiTokenAmount": {"amount": "5", "decimals": 6}},
            ],
            "innerInstructions": [{
                "index": 0,
                "instructions": [{
                    "program": "spl-token",
                    "programId": token_program,
                    "parsed": {
                        "type": "transferChecked",
                        "info": {"tokenAmount": {"amount": "5", "decimals": 6}},
                    },
                }],
            }],
            "api_key": "super-secret-test-value",
        },
        "request_url": "https://example.invalid/?api-key=super-secret-test-value",
    }


def required_token_fields_preserved(payload):
    instruction = payload["meta"]["innerInstructions"][0]["instructions"][0]
    return {
        "preTokenBalances_is_list": isinstance(payload["meta"]["preTokenBalances"], list),
        "postTokenBalances_is_list": isinstance(payload["meta"]["postTokenBalances"], list),
        "public_token_program_key_preserved": (
            payload["transaction"]["message"]["accountKeys"][0]
            == "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        ),
        "inner_instruction_program_id_preserved": (
            instruction["programId"] == "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        ),
        "parsed_token_amount_preserved": instruction["parsed"]["info"]["tokenAmount"] == {
            "amount": "5",
            "decimals": 6,
        },
    }
