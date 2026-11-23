"""The Section 34 outer limit, using the note date as a declaration-date proxy.

The actual declaration date and the date of an earlier annual return are not
recorded. Passing this check does not establish eligibility on those grounds.
"""

from datetime import date, datetime


def section34_warning(
    note_date: date | datetime | None,
    invoice_date: date | datetime | None,
    invoice_number: str,
) -> str | None:
    if note_date is None or invoice_date is None:
        return None
    if isinstance(note_date, datetime):
        note_date = note_date.date()
    if isinstance(invoice_date, datetime):
        invoice_date = invoice_date.date()
    fy_end_year = invoice_date.year + (invoice_date.month >= 4)
    if fy_end_year > date.max.year:
        return None
    deadline = date(fy_end_year, 11, 30)
    if note_date <= deadline:
        return None
    return (
        f"Invoice {invoice_number}: the note date {note_date.isoformat()} is after "
        f"the Section 34 outer deadline of {deadline.isoformat()}. This whole note "
        "is treated as a commercial credit note and excluded from GST reductions "
        "in GSTR-1 and GSTR-3B. Raise separate notes for invoices still within "
        "the deadline. The note date stands in for the declaration date; an "
        "earlier annual return deadline is not checked."
    )
