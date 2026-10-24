"""Pay-type vocabularies (#89), tenant-overridable.

``StudentRegistration.pay_type`` and ``HighSchool.hs_pay_type`` take their
choices from the callables below. A tenant replaces either list by defining
``REGISTRATION_PAY_TYPES`` / ``HIGHSCHOOL_PAY_TYPES`` in
``services/pay_types.py`` of its TENANT_SERVICES_APP (nnu adds State Funds).
A tenant without the module keeps the package lists.

The fields get the callables, not lists, so migrations record an import path
instead of labels and relabeling needs no migration (as ``hs_type_choices``).
The models' ``PAY_OPTIONS`` / ``PAY_TYPE_OPTIONS`` attributes resolve the same
lists on access, for code that reads them directly.
"""
from cis.services.tenant_services import get_tenant_override

DEFAULT_REGISTRATION_PAY_TYPES = [
    ('', '---'),
    ('student', 'Student Pay'),
    ('school_full', 'School Full Pay'),
    ('school_partial', 'School Partial Pay'),
]

DEFAULT_HIGHSCHOOL_PAY_TYPES = [
    ('', ''),
    ('Student Pay', 'Student Pay'),
    ('School Full Pay', 'School Full Pay'),
    ('School Partial Pay', 'School Partial Pay'),
]


def registration_pay_type_choices():
    return list(get_tenant_override('pay_types', 'REGISTRATION_PAY_TYPES')
                or DEFAULT_REGISTRATION_PAY_TYPES)


def highschool_pay_type_choices():
    return list(get_tenant_override('pay_types', 'HIGHSCHOOL_PAY_TYPES')
                or DEFAULT_HIGHSCHOOL_PAY_TYPES)


class LazyChoices:
    """A class attribute that resolves a choices callable on every access."""

    def __init__(self, resolve):
        self.resolve = resolve

    def __get__(self, instance, owner):
        return self.resolve()
