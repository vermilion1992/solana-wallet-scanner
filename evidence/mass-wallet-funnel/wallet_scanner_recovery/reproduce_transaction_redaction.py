#!/usr/bin/env python3
"""Reproduce a transaction-data redaction defect, without any network requests.

The redact_secrets implementation below is copied from
scanner/mass_search/capability.py at:
864a75b9d45d3318d3593c2dd4c9c9b9dd973e93

The input is deliberately SYNTHETIC. This script does not replay any live wallet,
import the application, access credentials, or fix the repository. A successful
run proves the current redactor removes legitimate transaction information.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def redact_secrets(value):
    """Exact implementation copied from the reviewed repository revision."""
    blocked = re.compile(r"(api[_-]?key|authorization|secret|token|password|credential)", re.I)
    if isinstance(value, dict):
        return {key: "[REDACTED]" if blocked.search(str(key)) else redact_secrets(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str) and len(value) >= 8 and blocked.search(value):
        return "[REDACTED]"
    return value


def reproduce() -> dict:
    token_program = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    # Structural fixture only: not a transaction and not profitable-wallet evidence.
    before = {
        "transaction": {
            "message": {"accountKeys": [token_program], "instructions": []}
        },
        "meta": {
            "err": None,
            "preTokenBalances": [
                {"accountIndex": 0, "uiTokenAmount": {"amount": "10", "decimals": 6}}
            ],
            "postTokenBalances": [
                {"accountIndex": 0, "uiTokenAmount": {"amount": "5", "decimals": 6}}
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
        },
    }
    after = redact_secrets(before)
    instruction = after["meta"]["innerInstructions"][0]["instructions"][0]
    checks = {
        "preTokenBalances_replaced": after["meta"]["preTokenBalances"] == "[REDACTED]",
        "postTokenBalances_replaced": after["meta"]["postTokenBalances"] == "[REDACTED]",
        "public_token_program_key_replaced": after["transaction"]["message"]["accountKeys"][0] == "[REDACTED]",
        "inner_instruction_program_id_replaced": instruction["programId"] == "[REDACTED]",
        "parsed_token_amount_replaced": instruction["parsed"]["info"]["tokenAmount"] == "[REDACTED]",
    }
    if not all(checks.values()):
        raise AssertionError("The copied implementation did not reproduce the expected corruption.")
    return {
        "result": "DESTRUCTIVE_REDACTION_REPRODUCED",
        "reviewed_commit": "864a75b9d45d3318d3593c2dd4c9c9b9dd973e93",
        "source_function": "scanner/mass_search/capability.py::redact_secrets",
        "input_kind": "SYNTHETIC_STRUCTURAL_FIXTURE",
        "network_requests": 0,
        "repository_modified": False,
        "live_wallets_replayed": 0,
        "checks": checks,
        "before": before,
        "after": after,
        "limitations": [
            "Not an import or test run of the full application.",
            "Does not confirm the contents or recoverability of the secure-box cache.",
            "Does not prove that this defect is the only cause of zero decoded swaps.",
            "Not a production fix, live grant, G3 pass, or profitability claim.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional path for the local JSON result.")
    args = parser.parse_args()
    result = reproduce()
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            parser.exit(2, f"Unable to write output: {exc}\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
