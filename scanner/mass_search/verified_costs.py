"""Documented tip and priority-fee recipients. Arbitrary SOL withdrawals are not tips."""

# Jito tip-payment accounts (published Jito tip distribution set).
JITO_TIP_ACCOUNTS = frozenset({
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
})
JITO_TIP_PROGRAM = "T1pyyaTNZsKv2WcRAB8oVnk93mLBw6NYZb1hEz6G5Vu"


def is_verified_tip_account(address):
    return address in JITO_TIP_ACCOUNTS or address == JITO_TIP_PROGRAM


def classify_native_withdrawal(destination):
    if is_verified_tip_account(destination):
        return "verified_tip"
    return "unresolved_debit"
