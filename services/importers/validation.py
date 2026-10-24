"""
Shared validation and result classes for importers.
"""
import datetime
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ValidationError:
    """Represents a validation error for a specific field"""
    field: str
    message: str


@dataclass
class ImportResult:
    """Structured result for each row import"""
    success: bool
    row_data: Dict
    error_message: Optional[str] = None
    validation_errors: List[ValidationError] = field(default_factory=list)

# ---------------------------------------------------------------------------
# Shared value coercion (#114 item 10)
#
# Reachable from both the Django student-import row form and the pydantic row
# schemas (class sections, high schools, instructors), so every importer reads
# a yes/no cell or a spreadsheet date the same way.
# ---------------------------------------------------------------------------

YES_WORDS = frozenset({'yes', 'y', 'true', 't', '1'})
NO_WORDS = frozenset({'no', 'n', 'false', 'f', '0'})

# Accepted date layouts (strptime), tried in order. %m/%d also accept unpadded
# digits, so '%m/%d/%Y' covers both MM/DD/YYYY and M/D/YYYY. %Y only matches a
# four-digit year. A deployment may replace the list with
# settings.IMPORT_DATE_INPUT_FORMATS.
DEFAULT_DATE_INPUT_FORMATS = ('%m/%d/%Y', '%m-%d-%Y', '%Y-%m-%d', '%Y/%m/%d')


def import_date_input_formats(default=DEFAULT_DATE_INPUT_FORMATS):
    """The deployment's accepted import date layouts, else `default`."""
    from django.conf import settings
    return tuple(getattr(settings, 'IMPORT_DATE_INPUT_FORMATS', None) or default)


def has_two_digit_year(text):
    """True for an all-numeric three-part date with no four-digit part
    ('5/2/11', '05-02-11'): one whose century has to be guessed."""
    if not isinstance(text, str):
        return False
    parts = re.split(r'[/\-.]', text.strip())
    return (len(parts) == 3 and all(p.isdigit() for p in parts)
            and not any(len(p) == 4 for p in parts))


def coerce_date(value, formats=None, allow_2digit_year=False):
    """Parse an import cell into a `date`.

    Blank (None, '' or whitespace) -> None; a date/datetime passes through.
    A string is tried against `formats` (default: import_date_input_formats()).
    Two-digit years are rejected unless `allow_2digit_year`, in which case
    each format is also tried with %y in place of %Y (strptime's pivot: 00-68
    -> 20xx, 69-99 -> 19xx). Raises ValueError naming the accepted layouts.
    """
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    if not text:
        return None

    formats = tuple(formats or import_date_input_formats())
    shown = ', '.join(_format_label(f) for f in formats)
    if has_two_digit_year(text):
        if not allow_2digit_year:
            raise ValueError(f'Use a four-digit year. Accepted formats: {shown}.')
        formats = tuple(f.replace('%Y', '%y') for f in formats if '%Y' in f)

    for fmt in formats:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f'Enter a real date as {shown}.')


def coerce_yes_no(value):
    """True / False for a yes/no cell (yes/no, y/n, true/false, t/f, 1/0, any
    case); None for a blank cell. Raises ValueError for anything else."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if not text:
        return None
    if text in YES_WORDS:
        return True
    if text in NO_WORDS:
        return False
    raise ValueError("Must be Yes or No (also Y/N, True/False, 1/0)")


_DATE_DIRECTIVES = (('%Y', 'YYYY'), ('%y', 'YY'), ('%m', 'MM'), ('%d', 'DD'))


def _format_label(fmt):
    for directive, word in _DATE_DIRECTIVES:
        fmt = fmt.replace(directive, word)
    return fmt


def import_option(module_name, attr, default):
    """An importer knob from the tenant's `module_name` service module, else
    `default` (a tenant without the module or the attribute keeps the package
    behaviour). Read at import time, never at module load."""
    from cis.services.tenant_services import get_tenant_override
    value = get_tenant_override(module_name, attr)
    return default if value is None else value
