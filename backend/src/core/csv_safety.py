"""Helpers for writing CSV files that people open in a spreadsheet."""


def csv_text(value: str | None) -> str:
    """Stop free text from running as a formula when the file opens in a spreadsheet."""
    text = value or ""
    return f"'{text}" if text[:1] in ("=", "+", "-", "@") else text
