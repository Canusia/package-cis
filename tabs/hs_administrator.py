"""HS Administrator detail-page tab content functions (see cis/tabs/teacher.py).
Eager-imported by myce/component_registry/hs_administrator.py so decorators run.
"""
from myce.component_registry.hs_administrator import hs_administrator_tabs  # noqa: F401

# Tab content functions are added in subsequent tasks.


@hs_administrator_tabs.tab(slug='passwd_reset', title='Password Reset', order=20,
                           template='cis/hs_admin/tabs/_passwd_reset.html')
def passwd_reset_tab(request, record):
    return {}


@hs_administrator_tabs.tab(slug='notes', title='Notes', order=30,
                           template='cis/hs_admin/tabs/_notes.html')
def notes_tab(request, record):
    from cis.models.note import HSAdministratorNote
    return {'notes': HSAdministratorNote.objects.filter(hsadmin=record.id).order_by('-createdon')}


@hs_administrator_tabs.tab(slug='highschools', title='High School Roles', order=10,
                           template='cis/hs_admin/tabs/_highschools.html',
                           lazy=False, active=True)
def highschools_tab(request, record):
    from cis.models.highschool_administrator import HSAdministratorPosition
    return {'roles': HSAdministratorPosition.objects.filter(hsadmin=record.id)}
