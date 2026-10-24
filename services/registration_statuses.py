"""Registration status labels (#90), tenant-overridable.

The stored status values belong to the package -- code, settings and reports
compare against them -- so a tenant can relabel a status but not add, drop or
rename one. A tenant's ``services/registration_statuses.py`` (in its
TENANT_SERVICES_APP) may define ``LABELS = {'approved': 'Ready for NNU
Review'}``; statuses it doesn't name keep the package label.

Keys are the current values. Migration 0071 renamed ``drop`` / ``wd`` to
``dropped`` / ``withdrawn``; the old keys are accepted as aliases so a tenant
carrying labels from before that rename still gets them.
"""
from cis.services.tenant_services import get_tenant_override

DEFAULT_REGISTRATION_STATUSES = (
    ('applied', 'Requested'),
    ('approved', 'Ready for Review'),
    ('not_approved', 'Not Approved by HS'),
    ('missing_prereq', 'Missing PreReq'),
    # A registration the student entered twice. Distinct from a denial on
    # purpose: closing duplicates out as 'not_approved' misreports the
    # school's approval rate. Carried in HVCC's own tree before the
    # extraction (ewu#47).
    ('duplicate', 'Duplicate Section'),
    ('pending_registration', 'Approved for Registration'),
    ('denied_registration', 'Not Approved for Registration'),
    ('registered', 'Registered'),
    ('enrolled', 'Enrolled'),
    ('dropped', 'Dropped'),
    ('withdrawn', 'Withdrawn'),
    ('app not processed', 'Application Not Processed-See Notes'),
)

RENAMED = {'drop': 'dropped', 'wd': 'withdrawn'}


def registration_status_choices():
    labels = {}
    for key, label in (get_tenant_override('registration_statuses', 'LABELS') or {}).items():
        labels[RENAMED.get(key, key)] = label
    return tuple((value, labels.get(value, label))
                 for value, label in DEFAULT_REGISTRATION_STATUSES)
