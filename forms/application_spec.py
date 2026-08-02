"""Resolve the per-tenant student-application field spec.

The spec lives in the tenant config app (settings.TABLE_CONFIGS_APP) as
`services/application_form.py`, which may export:

    APPLICATION_FIELDS   ordered list of field-definition dicts
    APPLICATION_RULES    list of cross-field rule dicts (see application_rules)
    validate(form, cleaned_data)   tenant-specific validation escape hatch
    VALIDATE_FIELDS      field names that validate() owns; the cis rules
                         covering them are skipped, so the tenant's check runs
                         INSTEAD of — not alongside — the shared rule
    post_save(form, student, commit)   the save-side counterpart of validate():
                         somewhere to put writes a storage target cannot
                         express, chiefly values DERIVED from another field's
                         answer. Runs after the fields are written but BEFORE
                         the commit, so whatever it sets is persisted.

Absent module → no spec → callers fall back to the legacy StudentProfileForm.
Keeps cis field-agnostic.
"""
import importlib

from django.conf import settings


def _spec_module():
    try:
        return importlib.import_module(
            f'{settings.TABLE_CONFIGS_APP}.services.application_form')
    except ModuleNotFoundError:
        return None


def get_application_fields():
    """Return the tenant's APPLICATION_FIELDS list, or None if undefined."""
    mod = _spec_module()
    if mod is None:
        return None
    return list(getattr(mod, 'APPLICATION_FIELDS', []) or [])


def get_application_rules():
    """Return the tenant's APPLICATION_RULES list ([] when it declares none)."""
    mod = _spec_module()
    if mod is None:
        return []
    return list(getattr(mod, 'APPLICATION_RULES', []) or [])


def get_tenant_validator():
    """Return (validate_callable_or_None, owned_field_names).

    A tenant needing validation cis should not carry exports `validate`; the
    field names in VALIDATE_FIELDS mark which shared rules it displaces.
    """
    mod = _spec_module()
    if mod is None:
        return None, frozenset()
    return getattr(mod, 'validate', None), frozenset(
        getattr(mod, 'VALIDATE_FIELDS', ()) or ())


def get_tenant_post_save():
    """Return the tenant's post_save(form, student, commit) callable, or None.

    The escape hatch for writes no storage target can express — a value derived
    from another field's answer, say "they ticked no_ssn, so record that they
    signed the waiver". `validate()` covers the validation half of "things cis
    should not carry"; this covers the save half.
    """
    mod = _spec_module()
    if mod is None:
        return None
    return getattr(mod, 'post_save', None)
