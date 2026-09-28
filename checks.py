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
from django.core.checks import Warning as CheckWarning, register


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
