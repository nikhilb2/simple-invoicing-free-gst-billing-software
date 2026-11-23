def contains_pattern(text: str) -> str:
    escaped = (
        text.strip()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"
