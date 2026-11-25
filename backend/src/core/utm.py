"""UTM campaign tags, cleaned and shaped for PostHog events.

The browser keeps the tags a visitor arrived with (frontend/src/lib/utm.ts) and
sends them with the few requests that matter for attribution: the WhatsApp
support click, registration, and the start of a Google sign-in. They arrive from
an untrusted client, so every entry point runs them through `clean_utm`.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

# utm_source, utm_medium, utm_campaign, utm_term, utm_content, utm_id and any
# other utm_* tag a campaign invents. Anything else is dropped.
_UTM_KEY = re.compile(r"^utm_[a-z0-9_]{1,40}$")
MAX_UTM_KEYS = 20
MAX_UTM_VALUE_LENGTH = 200


def clean_utm(utm: Mapping[str, Any] | None, max_keys: int = MAX_UTM_KEYS) -> dict[str, str]:
    """Keeps well-formed utm_* keys with non-blank string values, trimmed and capped."""
    cleaned: dict[str, str] = {}
    for key, value in (utm or {}).items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        key = key.strip().lower()
        if not _UTM_KEY.match(key):
            continue
        value = value.strip()[:MAX_UTM_VALUE_LENGTH]
        if value:
            cleaned[key] = value
        if len(cleaned) >= max_keys:
            break
    return cleaned


def utm_event_properties(utm: Mapping[str, str]) -> dict[str, Any]:
    """Event properties for already-cleaned tags: the utm_* keys themselves, and
    `$set_once` with the matching `$initial_utm_*` person properties.

    posthog-python does not derive `$initial_*` from utm_* event properties the
    way posthog-js does, so a sign-up would never fill `$initial_utm_source`
    unless it is set explicitly. `$set_once` keeps the first touch if the person
    already has one. Empty when there are no tags, so callers can always splat it.
    """
    if not utm:
        return {}
    return {
        **utm,
        "$set_once": {f"$initial_{key}": value for key, value in utm.items()},
    }
