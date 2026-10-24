"""System checks for the cis app.

PT-31: surface a missing Stripe webhook signing secret. An empty/unset
STRIPE_WEBHOOK_SECRET lets forged webhook events verify against an empty-key
HMAC. The webhook endpoint (cis.views.home.stripe_webhook) fails closed at
runtime regardless; this check additionally warns at startup/deploy so the
misconfiguration is visible. It is a Warning (not an Error) so it does not
block management commands / CI in environments where the secret isn't set.

W006 (package-cis#77): django's plain ModelBackend must not be listed in
AUTHENTICATION_BACKENDS. It checks username + password without the PT-40
lockout, so a locked account refused by EmailAuthBackend would sign in through
it. EmailAuthBackend covers username logins itself. A Warning, so a tenant that
pins this cis before editing its settings still builds and migrates.

E004 / W009 (package-cis#100): sibling apps cis imports. E004 names a
required one that is missing (cis cannot run without it); W009 names an
optional one whose features are skipped without it.

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


PLAIN_MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'


@register()
def lockout_bypass_backend_check(app_configs, **kwargs):
    if PLAIN_MODEL_BACKEND not in settings.AUTHENTICATION_BACKENDS:
        return []
    return [
        CheckWarning(
            f'{PLAIN_MODEL_BACKEND} is in AUTHENTICATION_BACKENDS.',
            hint=(
                'Remove it from myce/settings.py. It signs in locked accounts '
                'on username + password, bypassing the PT-40 login lockout '
                '(package-cis#77). cis.email_backend.EmailAuthBackend already '
                'handles username logins such as /ce/ldap/.'
            ),
            id='cis.W006',
        )
    ]


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


def _optional_users_tab_check(module_name, tab, files, check_id):
    """Warn when the tenant has not shipped the table config for an opt-in
    /ce/users/ tab. Same contract as W005: without it the tab is not shown."""
    app = getattr(settings, 'TABLE_CONFIGS_APP', 'myce_tenant_configs')
    module = f'{app}.services.{module_name}'
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
                f'cis expects the tenant to ship {files} for the {tab} tab on '
                f'/ce/users/ (copy them from Canusia/ewu). Without them the tab '
                f'is not shown.'
            ),
            id=check_id,
        )
    ]


@register()
def login_log_table_check(app_configs, **kwargs):
    """W007: the Login Log tab's table config on /ce/users/."""
    return _optional_users_tab_check(
        'login_log_table', 'Login Log',
        'login_log_table.py, users/_login_log_table.html and js/login_log_table.js',
        'cis.W007')


@register()
def saml_log_table_check(app_configs, **kwargs):
    """W008: the SAML Attributes tab's table config on /ce/users/. Silent on
    a tenant without the sp app, which never shows the tab."""
    from django.apps import apps
    if not apps.is_installed('sp'):
        return []
    return _optional_users_tab_check(
        'saml_log_table', 'SAML Attributes',
        'saml_log_table.py, users/_saml_log_table.html and js/saml_log_table.js',
        'cis.W008')


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


# Sibling apps cis imports (#100). The required ones cannot be routed around:
# pd_event backs migration 0002 and EventNote.event, and every charge, payment
# and balance cis computes is a StudentTransaction row. alerts is optional --
# its alerts are fire-and-forget and go through cis/integrations/alerts.py.
# ethos and grades are optional through cis/integrations/ too, and stay
# silent: most tenants run without them on purpose.
REQUIRED_SIBLING_APPS = {
    'pd_event': 'cis migration 0002 and EventNote.event reference pd_event.Event',
    'student_transactions': ('student charges, payments, balances and the '
                             'transactions report are StudentTransaction rows'),
}
OPTIONAL_SIBLING_APPS = {
    'alerts': ('in-app alerts for note replies and instructor-application '
               'status changes are not created'),
}


@register()
def sibling_apps_check(app_configs, **kwargs):
    """E004 / W009 (#100): a sibling app cis imports is not installed."""
    from django.apps import apps
    messages = []
    for label, why in REQUIRED_SIBLING_APPS.items():
        if label not in apps.app_configs:
            messages.append(CheckError(
                f"cis requires the '{label}' app, which is not in INSTALLED_APPS.",
                hint=f'Install and add it: {why}.',
                id='cis.E004'))
    for label, effect in OPTIONAL_SIBLING_APPS.items():
        if label not in apps.app_configs:
            messages.append(CheckWarning(
                f"The '{label}' app is not in INSTALLED_APPS.",
                hint=f'cis runs without it, but {effect}.',
                id='cis.W009'))
    return messages
