"""Read-only overview of the settings behind a journey (e.g. student registration)."""
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404
from django.shortcuts import render

from cis.menu import draw_menu, cis_menu
from cis.services.settings_overview import build_overview
from cis.campus_gate import can_manage_settings as _can_manage_settings


@login_required
@user_passes_test(_can_manage_settings, login_url='/')
def settings_overview_page(request, profile):
    try:
        overview = build_overview(profile, request=request)
    except (KeyError, ImportError, AttributeError):
        raise Http404('Unknown settings profile')
    menu = draw_menu(cis_menu, *overview['menu'])
    return render(request, 'cis/settings_overview.html', {
        'menu': menu,
        'overview': overview,
        'profile': profile,
    })
