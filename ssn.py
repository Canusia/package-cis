"""Who may see or change another person's SSN (MC-14, package-cis #38).

Two global Django permissions on CustomUser: cis.view_ssn and cis.change_ssn.
They say *what* a staff member may do; campus membership separately says
*where*. ssn_access(user) is the one place that reads them, and every
staff-facing exposure -- the CE student edit form, the student API, the
students-by-date report -- asks it.

Deny by default: without view_ssn the field is removed, never rendered and
hidden. With view_ssn but not change_ssn it is read-only.

Not gated, on purpose:
- a student or applicant entering their own SSN on their own form;
- system integrations such as the SIS export (undup_students) and a tenant's
  Banner push, which are not a person looking at someone's SSN.
"""
NONE = 'none'
VIEW = 'view'
CHANGE = 'change'

SSN_FIELDS = ('ssn', 'verify_student_ssn')


def ssn_access(user):
    if user is None or not getattr(user, 'is_authenticated', False):
        return NONE
    if user.has_perm('cis.change_ssn'):
        return CHANGE
    if user.has_perm('cis.view_ssn'):
        return VIEW
    return NONE


def restrict_form(form, user):
    """Drop or lock the SSN fields on a staff-facing form."""
    access = ssn_access(user)
    for name in SSN_FIELDS:
        if name not in form.fields:
            continue
        if access == NONE:
            del form.fields[name]
        elif access == VIEW:
            form.fields[name].disabled = True
    return access
