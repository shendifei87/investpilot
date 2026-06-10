"""Shared utility functions for analysis modules."""

from __future__ import annotations


def coerce_float(value, default: float | None = None) -> float | None:
    """Best-effort float coercion for values like '12.5%', '18x', '1,234'.

    Returns *default* when conversion fails or input is None/bool/empty string.
    Percentage values (ending with '%') are divided by 100.
    Trailing 'x'/'X' (PE multiples) are stripped as a suffix, not via rstrip
    which would remove all trailing characters from the set.
    """
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return default
        # Detect and remove suffix markers
        is_pct = text.endswith("%")
        if is_pct or text.endswith("x") or text.endswith("X"):
            text = text[:-1]
        try:
            num = float(text)
        except ValueError:
            return default
        return num / 100 if is_pct else num
    return default


def is_pct_variable(name: str) -> bool:
    """Return True if *name* is a percentage-type variable by naming convention.

    Matches names ending with: _margin, _growth, _ratio, _pct, _rate, _yoy, _qoq.
    Suffix-only matching avoids misclassifying non-pct names that happen to
    contain a suffix as a substring (e.g. interest_rate_on_debt contains
    ``_rate`` but is a rate parameter, not a percentage variable).
    """
    n = name.lower().strip()
    pct_suffixes = ("_margin", "_growth", "_ratio", "_pct", "_rate", "_yoy", "_qoq")
    return any(n.endswith(s) for s in pct_suffixes)
