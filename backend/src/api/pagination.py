"""Shared bounds for paginated list endpoints."""

# Keeps (page - 1) * page_size inside the 64-bit OFFSET the databases use.
MAX_PAGE = 1_000_000
