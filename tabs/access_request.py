"""Access Request detail-page tab content functions (see cis/tabs/hs_administrator.py).
Eager-imported by myce/component_registry/access_request.py so decorators run.
"""
from myce.component_registry.access_request import access_request_tabs  # noqa: F401

# Tab content functions are added in subsequent tasks.


@access_request_tabs.tab(slug='additional_info', title='Additional Information', order=10,
                         template='cis/hs_admin/tabs/_access_request_additional_info.html',
                         lazy=False, active=True)
def additional_info_tab(request, record):
    from cis.models.highschool_administrator import HSAdministratorPosition
    return {'administrators': HSAdministratorPosition.objects.filter(highschool=record.highschool)}
