"""System checks for the cis app.

PT-31: surface a missing Stripe webhook signing secret. An empty/unset
STRIPE_WEBHOOK_SECRET lets forged webhook events verify against an empty-key
HMAC. The webhook endpoint (cis.views.home.stripe_webhook) fails closed at
runtime regardless; this check additionally warns at startup/deploy so the
misconfiguration is visible. It is a Warning (not an Error) so it does not
block management commands / CI in environments where the secret isn't set.
"""
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
