"""Recommendation form resolution per campus (package-cis#66).

The same opt-in pattern as the FERPA form hook (#65): a tenant may define
``recommendation_form.get_form_class(campus)`` to ship a different form per
campus; otherwise its ``StudentRecommendationForm`` is used.
"""
import inspect

from cis.services.tenant_services import get_tenant_override, get_tenant_service


def _campus(campus):
    if campus is not None:
        return campus
    from cis.campus_context import current_campus_or_none
    return current_campus_or_none()


def recommendation_form_class(campus=None):
    """The tenant's recommendation form class for `campus` (default: current)."""
    hook = get_tenant_override('recommendation_form', 'get_form_class')
    if hook is not None:
        return hook(_campus(campus))
    return get_tenant_service('recommendation_form').StudentRecommendationForm


def build_recommendation_form(student, registrations, *args, campus=None, **kwargs):
    """Instantiate the campus's form, passing campus= only if it accepts it."""
    form_class = recommendation_form_class(campus)
    try:
        accepts = 'campus' in inspect.signature(form_class.__init__).parameters
    except (TypeError, ValueError):
        accepts = False
    if accepts:
        kwargs['campus'] = _campus(campus)
    return form_class(student, registrations, *args, **kwargs)
