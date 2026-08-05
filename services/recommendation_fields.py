"""What a tenant's recommendation form actually asks.

The recommendation form itself resolves through
``get_tenant_service('recommendation_form')``, but the consumers of the stored
answers -- the export report, the DRF payload -- used to carry a fixed list of
one tenant's Pennsylvania field names (Keystone Exam, PSSA, GEIP). Any tenant
with a different rec form got those as permanently-empty columns and had no way
to surface its own answers without editing ``cis`` (ewu#49).

The tenant form's own declared fields are the contract. A tenant that wants
explicit control can export ``export_fields()`` from its
``recommendation_form`` service module, returning ``{name: label}``; otherwise
the list is derived from ``StudentRecommendationForm.base_fields``.
"""
from django import forms

from cis.services.tenant_services import get_tenant_service

#: Plumbing carried by every rec form: identity the export already has columns
#: for, and the upload-blurb label, which is configuration rather than an
#: answer.
STRUCTURAL_FIELDS = frozenset({
    'id', 'student', 'term', 'student_state_id', 'upload_label',
})


def _prettify(name):
    return name.replace('_', ' ').title()


def recommendation_export_fields():
    """Return ``{field_name: label}`` for the tenant's recommendation answers.

    Ordered as the tenant declares them. Returns ``{}`` if the tenant ships no
    recommendation_form service, so a caller can carry on with its own
    identity columns rather than raising.
    """
    try:
        service = get_tenant_service('recommendation_form')
    except (ImportError, AttributeError):
        return {}

    # A form label is a question put to a counselor; it makes a poor CSV
    # header. A tenant that cares about its export names its own columns.
    explicit = getattr(service, 'export_fields', None)
    if callable(explicit):
        return dict(explicit())

    form = getattr(service, 'StudentRecommendationForm', None)
    if form is None:
        return {}

    fields = {}
    for name, field in getattr(form, 'base_fields', {}).items():
        if name in STRUCTURAL_FIELDS:
            continue
        # An upload has no meaningful CSV cell, and the export already carries
        # its own download handling.
        if isinstance(field, forms.FileField):
            continue
        fields[name] = str(field.label or _prettify(name))

    return fields
