"""System checks for the cis app.

PT-31: surface a missing Stripe webhook signing secret. An empty/unset
STRIPE_WEBHOOK_SECRET lets forged webhook events verify against an empty-key
HMAC. The webhook endpoint (cis.views.home.stripe_webhook) fails closed at
runtime regardless; this check additionally warns at startup/deploy so the
misconfiguration is visible. It is a Warning (not an Error) so it does not
block management commands / CI in environments where the secret isn't set.

W002 (v0.0.42+): the tenant's table-config app should ship
`services/document_types_table.py` for the CE Document Types page. The page
falls back to a plain list without it, so this warns rather than errors.
"""
import importlib.util

from django.conf import settings
from django.core.checks import Error as CheckError, Warning as CheckWarning, register

from cis.services.tenant_services import get_tenant_service


@register()
def stripe_webhook_secret_check(app_configs, **kwargs):
    secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)
    if not secret:
        return [
            CheckWarning(
                'STRIPE_WEBHOOK_SECRET is empty or unset.',
                hint=(
                    'Provide a non-empty Stripe webhook signing secret '
                    '(SECRETS["STRIPE_WEBHOOK_SECRET"]) in every environment. '
                    'The /webhooks/stripe/ endpoint fails closed without it.'
                ),
                id='cis.W001',
            )
        ]
    return []


@register()
def document_types_table_check(app_configs, **kwargs):
    app = getattr(settings, 'TABLE_CONFIGS_APP', 'myce_tenant_configs')
    module = f'{app}.services.document_types_table'
    try:
        found = importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        found = False
    if found:
        return []
    return [
        CheckWarning(
            f'{module} is missing.',
            hint=(
                'cis v0.0.42+ expects the tenant to ship document_types_table.py, '
                '_document_types_table.html and js/document_types_table.js for the '
                'CE Document Types page (copy them from Canusia/ewu). Without them '
                'the page falls back to a plain, unsortable list.'
            ),
            id='cis.W002',
        )
    ]


@register()
def hs_uploads_table_check(app_configs, **kwargs):
    """W003 (v0.0.43+): the High School Uploads tab's table config (#56)."""
    app = getattr(settings, 'TABLE_CONFIGS_APP', 'myce_tenant_configs')
    module = f'{app}.services.hs_uploads_table'
    try:
        found = importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        found = False
    if found:
        return []
    return [
        CheckWarning(
            f'{module} is missing.',
            hint=(
                'cis v0.0.43+ expects the tenant to ship hs_uploads_table.py, '
                '_hs_uploads_table.html and js/hs_uploads_table.js for the High '
                'School Uploads tab on /ce/students/support_docs/ (copy them from '
                'Canusia/ewu). Without them the tab shows a plain list of the '
                'latest uploads, with no filters or review actions.'
            ),
            id='cis.W003',
        )
    ]


@register()
def roleless_users_table_check(app_configs, **kwargs):
    """W005 (package-cis #71): the No Role tab's table config on /ce/users/."""
    app = getattr(settings, 'TABLE_CONFIGS_APP', 'myce_tenant_configs')
    module = f'{app}.services.roleless_users_table'
    try:
        found = importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        found = False
    if found:
        return []
    return [
        CheckWarning(
            f'{module} is missing.',
            hint=(
                'cis expects the tenant to ship roleless_users_table.py, '
                'users/_roleless_table.html and js/roleless_users_table.js for the '
                'No Role tab on /ce/users/ (copy them from Canusia/ewu). Without '
                'them /ce/users/ shows only the CE Users table, with no tab for '
                'accounts that hold no role.'
            ),
            id='cis.W005',
        )
    ]


@register()
def branding_check(app_configs, **kwargs):
    """E001-E003, W004 (package-cis #61): the tenant's per-campus branding map
    (``services/branding.py``'s ``BRANDS``) -- every asset must exist, every key
    be known and every colour be safe, caught at build time rather than as a
    broken logo in production."""
    from django.contrib.staticfiles import finders
    from cis.branding import brand_problems

    try:
        brands = getattr(get_tenant_service('branding'), 'BRANDS', None)
    except ModuleNotFoundError:
        return []
    if not isinstance(brands, dict):
        return []

    messages = []
    for code, entry in brands.items():
        for key in ('logo', 'background', 'favicon'):
            path = entry.get(key)
            if path and not finders.find(path):
                messages.append(CheckError(
                    f'Branding for {code}: {key} {path!r} is not a static file.',
                    id='cis.E001'))
        for check_code, message in brand_problems(entry):
            messages.append(CheckError(
                f'Branding for {code}: {message}.', id=f'cis.{check_code}'))

    try:
        from cis.models.course import Campus
        known = set(Campus.objects.filter(code__in=list(brands)).values_list('code', flat=True))
    except Exception:  # no database yet (image build, fresh checkout)
        return messages
    for code in sorted(set(brands) - known):
        messages.append(CheckWarning(
            f'Branding for {code}: no campus has this code.', id='cis.W004'))
    return messages
