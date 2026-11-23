"""Default used when older company records have no currency configured."""

DEFAULT_CURRENCY_CODE = "INR"


def resolve_currency_code(value: str | None) -> str:
    return (value or "").strip() or DEFAULT_CURRENCY_CODE
