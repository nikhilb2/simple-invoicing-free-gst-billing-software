"""Decode an uploaded CSV that may have been saved by Excel on Windows."""

import codecs

EXCEL_FILE_MESSAGE = (
    "This is an Excel file, not a CSV. In Excel choose File → Save As → "
    "CSV UTF-8 (Comma delimited), then import that file."
)
UNREADABLE_MESSAGE = (
    "This file could not be read. In Excel choose File → Save As → "
    "CSV UTF-8 (Comma delimited), then import that file."
)

# .xlsx/.xlsm/.ods are zip files; .xls is an OLE2 compound file.
_EXCEL_SIGNATURES = (b"PK\x03\x04", b"\xd0\xcf\x11\xe0")


class CsvDecodeError(ValueError):
    """The upload cannot be read as CSV; str(exc) is safe to show to the user."""


def decode_csv_upload(content: bytes) -> tuple[str, str]:
    """Return (text, delimiter) for an uploaded CSV.

    Order: Excel binary check, UTF-16 (BOM), UTF-8 (with or without BOM), then
    Windows-1252, which is what Excel's "CSV (Comma delimited)" writes on Windows.
    The delimiter is a tab for Excel's "Unicode Text" / "Text (Tab delimited)"
    files and a comma otherwise.
    """
    if content.startswith(_EXCEL_SIGNATURES):
        raise CsvDecodeError(EXCEL_FILE_MESSAGE)

    if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            # The "utf-16" codec reads the BOM and drops it.
            text = content.decode("utf-16")
        except UnicodeDecodeError as exc:
            raise CsvDecodeError(UNREADABLE_MESSAGE) from exc
    else:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            # cp1252 leaves 5 bytes undefined (0x81, 0x8D, 0x8F, 0x90, 0x9D).
            # Replace just those with U+FFFD rather than refuse the whole file.
            text = content.decode("cp1252", errors="replace")

    return text, _delimiter(text)


def _delimiter(text: str) -> str:
    header = text.split("\n", 1)[0]
    return "\t" if header.count("\t") > header.count(",") else ","
