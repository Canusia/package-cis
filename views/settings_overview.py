"""Read-only overview of the settings behind a journey (e.g. student registration)."""
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404
from django.shortcuts import render

from cis.menu import draw_menu, cis_menu
from cis.services.settings_overview import build_overview
from cis.utils import user_has_cis_role


def _can_manage_settings(user):
    return user_has_cis_role(user) or getattr(user, 'is_superuser', False)


@login_required
@user_passes_test(_can_manage_settings, login_url='/')
def settings_overview_page(request, profile):
    try:
        overview = build_overview(profile, request=request)
    except KeyError:
        raise Http404('Unknown settings profile')
    menu = draw_menu(cis_menu, 'students', 'students')
    return render(request, 'cis/settings_overview.html', {
        'menu': menu,
        'overview': overview,
        'profile': profile,
    })
