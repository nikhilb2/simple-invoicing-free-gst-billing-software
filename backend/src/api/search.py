"""Helpers for search query construction.

LIKE/ILIKE treat % and _ as wildcards. Escape them so a search term matches
literally.
"""


def contains_pattern(text: str) -> str:
    """Return a contains pattern for ilike/like with wildcards escaped.

    Escapes \\, % and _ so that the pattern matches the literal characters.
    Leading and trailing % make it a contains match.
    """
    escaped = (
        text.strip()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"
