"""FERPA consent per campus (package-cis#65).

One StudentFerpa per (student, campus). Every FERPA check goes through here,
so "which campus" is decided in one place.
"""


def resolve_campus(campus=None):
    if campus is not None:
        return campus
    from cis.campus_context import current_campus_or_none
    return current_campus_or_none()
