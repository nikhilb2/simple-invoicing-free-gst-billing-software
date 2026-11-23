"""Refuses a NUL character anywhere in a request, instead of a 500 from Postgres.

Postgres cannot store or compare text containing a NUL character (``\\0``): the
column type accepts it over the wire, then the query fails server-side. A NUL
turns up without anyone meaning harm -- text pasted from some PDFs, or a field
from software that null-terminates strings -- and the API passed it straight
through to the database, turning an ordinary request into a 500.

Fixing this field by field would touch every schema that takes free text, searches
or filters. One check in a single place, wired in once as a global dependency
(see ``app_main.py``), covers all of them instead.
"""

import email.message
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request

NUL = "\x00"


def _contains_nul(value: object) -> bool:
    """Whether a NUL character appears anywhere in a JSON-decoded value.

    Iterative on purpose: ``json.loads`` accepts nesting several hundred levels
    deep, which a recursive walk would turn into a RecursionError (a 500).
    """
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            if NUL in current:
                return True
        elif isinstance(current, dict):
            for key, item in current.items():
                if isinstance(key, str) and NUL in key:
                    return True
                stack.append(item)
        elif isinstance(current, list):
            stack.extend(current)
    return False


def _refuse(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def _is_json_body(content_type: str | None) -> bool:
    """Mirror FastAPI 0.115's rule for when it JSON-decodes a request body.

    A missing content-type, ``application/json`` and any ``application/*+json``
    are all decoded as JSON by FastAPI, so all of them must be scanned.
    """
    if not content_type:
        return True
    message = email.message.Message()
    message["content-type"] = content_type
    if message.get_content_maintype() != "application":
        return False
    subtype = message.get_content_subtype()
    return subtype == "json" or subtype.endswith("+json")


async def reject_nul_characters(request: Request) -> None:
    """Refuse a NUL character in query params, path params, a JSON body or a
    form-encoded body, with a 422.

    Covered: query string, path parameters, JSON bodies (FastAPI's own
    content-type rule) and ``application/x-www-form-urlencoded`` bodies.

    Not covered, on purpose: multipart uploads. The backup restore/preflight
    files are binary and must never be scanned; its one text field
    (``confirm_text``) is only compared to the word RESTORE and never reaches
    the database. The product CSV import checks each row itself.

    Starlette URL-decodes query and path parameters before we see them, so
    ``%00`` already reads as ``\\0``. A JSON body carries an embedded NUL as
    the escape ``\\u0000``, never a raw 0x00 byte, so the body is decoded
    first. ``request.json()`` caches its result on the request, so FastAPI's
    own body parsing later reuses it and the body is parsed only once.

    This runs before authentication, so an unauthenticated request carrying a
    NUL gets 422 rather than 401. That leaks nothing (the message is generic and
    names only a parameter the caller sent), and moving it after
    auth is invasive: auth is a per-route dependency and several routes are
    public (login, OAuth, public share pages) and need the check too.
    """
    for key, value in request.query_params.multi_items():
        if NUL in key or NUL in value:
            raise _refuse(
                f"Query parameter {key!r} contains a character that is not "
                "allowed: NUL (\\u0000)."
            )

    for key, value in request.path_params.items():
        if _contains_nul(key) or _contains_nul(value):
            raise _refuse(
                f"Path parameter {key!r} contains a character that is not "
                "allowed: NUL (\\u0000)."
            )

    content_type = request.headers.get("content-type")
    media_type = (content_type or "").split(";", 1)[0].strip().lower()

    if media_type == "application/x-www-form-urlencoded":
        body = await request.body()
        try:
            pairs = parse_qsl(body.decode("utf-8", errors="replace"), keep_blank_values=True)
        except ValueError:
            return
        if _contains_nul([item for pair in pairs for item in pair]):
            raise _refuse("This request contains a character that is not allowed: NUL (\\u0000).")
        return

    if not _is_json_body(content_type):
        return

    body = await request.body()
    if not body:
        return

    try:
        parsed = await request.json()
    except (ValueError, RecursionError):
        # Malformed or absurdly nested JSON: let FastAPI respond as it would.
        return

    if _contains_nul(parsed):
        raise _refuse("This request contains a character that is not allowed: NUL (\\u0000).")
