"""Validated settings, fixed free-only invariants, and backend-only credentials."""
from datetime import date
from decimal import Decimal, InvalidOperation
import os
import re

STRICT = {
    "name": "Strict research", "version": "strict-v0.3", "window_days": 30, "verification_days": 90,
    "min_profit_sol": "5", "min_realised_roi_pct": "10", "min_median_roi_pct": "5",
    "min_win_rate_pct": "50", "max_win_rate_pct": "85", "min_hold_hours": "1", "max_hold_hours": "72",
    "min_positions": 50, "min_positions_90d": 100, "min_mints": 20, "max_mints": 100,
    "max_rapid_sale_pct": "10", "min_avg_buys": "1", "max_avg_buys": "2", "min_avg_sells": "1",
    "max_avg_sells": "3", "min_positive_weeks": 3, "max_contribution_pct": "25",
    "require_positive_economic_pnl": True,
}
LIMITS = {"candidate_cap": 20, "deep_audit_cap": 5, "transaction_limit": 10000,
          "wallet_credit_limit": 20000, "helius_cap": 800000, "discovery_pause": 600000,
          "min_free_disk_mb": 2048}


def validate_address(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", value):
        raise ValueError("Enter a valid public Solana address")
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = 0
    for character in value:
        number = number * 58 + alphabet.index(character)
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big")
    zeros = len(value) - len(value.lstrip("1"))
    if len(raw) + zeros != 32:
        raise ValueError("Public address must decode to 32 bytes")
    return value


def validate_preset(changes, current=None):
    if not isinstance(changes, dict) or set(changes) - set(STRICT):
        raise ValueError("Unknown preset setting")
    result = {**(current or STRICT), **changes}
    for key, baseline in STRICT.items():
        value = result[key]
        if isinstance(baseline, bool):
            if type(value) is not bool:
                raise ValueError(f"{key} must be a boolean")
        elif type(baseline) is int:
            if type(value) is not int or value < 0 or value > 100000:
                raise ValueError(f"Invalid {key}")
        elif key not in ("name", "version"):
            if not isinstance(value, str) or len(value) > 32 or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
                raise ValueError(f"{key} must be a decimal string")
            try:
                number = Decimal(value)
            except InvalidOperation as error:
                raise ValueError(f"Invalid {key}") from error
            if not number.is_finite() or number < 0 or number > 1000000:
                raise ValueError(f"Invalid {key}")
        elif not isinstance(value, str) or not 1 <= len(value) <= 80:
            raise ValueError(f"Invalid {key}")
    for lower, upper in (("min_win_rate_pct", "max_win_rate_pct"), ("min_hold_hours", "max_hold_hours"), ("min_avg_buys", "max_avg_buys"), ("min_avg_sells", "max_avg_sells"), ("min_mints", "max_mints")):
        if Decimal(str(result[lower])) > Decimal(str(result[upper])):
            raise ValueError(f"{lower} cannot exceed {upper}")
    for key in ("min_win_rate_pct", "max_win_rate_pct", "max_rapid_sale_pct", "max_contribution_pct"):
        if Decimal(result[key]) > 100:
            raise ValueError(f"{key} cannot exceed 100%")
    if not 1 <= result["window_days"] <= 365 or not result["window_days"] <= result["verification_days"] <= 365:
        raise ValueError("Report window must be 1–365 days and fit within verification history")
    if result["min_positive_weeks"] > 4:
        raise ValueError("Positive weeks cannot exceed four")
    return result


def validate_limits(changes, current=None):
    if not isinstance(changes, dict) or set(changes) - set(LIMITS):
        raise ValueError("Unknown workload control")
    result = {**(current or LIMITS), **changes}
    for key, value in result.items():
        maximum = LIMITS[key] if key != "min_free_disk_mb" else 1000000
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f"{key} must be between 1 and {maximum}; free-mode caps cannot be raised")
    if result["deep_audit_cap"] > result["candidate_cap"] or result["discovery_pause"] > result["helius_cap"]:
        raise ValueError("Audit and discovery thresholds must fit within their caps")
    return result


class Credentials:
    """Use an OS credential backend if available; otherwise keep keys in RAM only."""
    def __init__(self, account):
        self.account = account
        self.key = os.environ.get("HELIUS_API_KEY")
        self.storage = "environment" if self.key else "none"
        self.backend = None
        try:
            import keyring
            backend = keyring.get_keyring()
            approved = ("keyring.backends.macOS", "keyring.backends.Windows", "keyring.backends.SecretService", "keyring.backends.kwallet")
            if any(type(backend).__module__.startswith(name) for name in approved):
                self.backend = keyring
                if not self.key:
                    self.key = keyring.get_password("solana-wallet-scanner", self.account)
                    self.storage = "os-keyring" if self.key else "none"
        except Exception:
            self.backend = None

    def set(self, key):
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,200}", key):
            raise ValueError("Invalid Helius API key format")
        self.key = key
        self.storage = "session-only"
        if self.backend:
            try:
                self.backend.set_password("solana-wallet-scanner", self.account, key)
                self.storage = "os-keyring"
            except Exception:
                self.storage = "session-only"


def validate_cycle(start, end):
    try:
        lower, upper = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError) as error:
        raise ValueError("Enter the provider billing-cycle dates (YYYY-MM-DD)") from error
    if not lower <= date.today() < upper or not 1 <= (upper - lower).days <= 40:
        raise ValueError("The provider cycle must contain today and last at most 40 days")
    return start, end
