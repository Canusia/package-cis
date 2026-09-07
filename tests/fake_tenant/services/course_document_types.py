"""A stand-in Course Document vocabulary for tests.

The real vocabulary is tenant-owned and resolved through
``get_tenant_service('course_document_types')`` — that is the entire point of
``course_document_choices()``. A test asserting specific labels could therefore
only pass on the tenant that happens to define them, and the shipped `cis` suite
runs on every tenant that adopts the package.

Tests that need concrete codes pin this module with
``override_settings(TENANT_SERVICES_APP='cis.tests.fake_tenant')`` and assert
against these values, so they exercise the mechanism rather than one
deployment's wording.

Implements the full service interface `cis` calls, mirroring a real tenant
module: a fixture that covers only part of the seam fails later and further
from the cause.
"""

DOCUMENT_TYPES = [
    ('doc_a', 'Document A'),
    ('doc_b', 'Document B'),
    ('doc_c', 'Document C'),
]


def choices():
    """[(code, label), ...] for model/form choices."""
    return list(DOCUMENT_TYPES)


def codes():
    """Valid stored values."""
    return [code for code, _ in DOCUMENT_TYPES]


def label_for(code):
    """Display label for a code, falling back to the code itself.

    Falling back rather than raising matches the real modules: a code retired
    from the vocabulary must not break pages showing requirements still
    carrying it.
    """
    for candidate, label in DOCUMENT_TYPES:
        if candidate == code:
            return label
    return code


def labels(values):
    """Map a list of stored codes to display labels."""
    return [label_for(code) for code in (values or [])]


def normalize(value):
    """Accept a code or a label (case-insensitive) and return the code.

    Returns None when unrecognised, so callers decide whether that is an error
    or a silent skip.
    """
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    for code, label in DOCUMENT_TYPES:
        if candidate == code or candidate.lower() == label.lower():
            return code
    return None
