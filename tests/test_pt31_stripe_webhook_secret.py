"""PT-31: a system check must require a non-empty STRIPE_WEBHOOK_SECRET.

The endpoint-level fail-closed tests (StripeWebhookFailClosedTests: empty
secret -> 500 with no StudentTransaction written, unset secret -> 500, bad
signature -> 400) were removed here. They called reverse('stripe_webhook'),
and the route is host wiring — `myce/urls.py`, per tenant — so they errored in
NoReverseMatch on any deployment that has not wired the webhook. ewu has it
commented out (`myce/urls.py:268`), so all three errored on every run.

The view itself (`cis.views.home.stripe_webhook`) still ships and still fails
closed; what is gone is the regression test proving it. A tenant that DOES wire
the endpoint now has no automated check that a missing secret cannot reach
signature verification or business logic. `git log` this file to recover them —
they only need the reverse() replaced with a hardcoded path, or a skip when the
URL name does not resolve. See ewu#34.
"""
from django.test import SimpleTestCase, override_settings


class StripeWebhookSecretCheckTests(SimpleTestCase):
    def _run(self):
        from cis.checks import stripe_webhook_secret_check
        return stripe_webhook_secret_check(app_configs=None)

    @override_settings(STRIPE_WEBHOOK_SECRET='')
    def test_empty_secret_warns(self):
        errors = self._run()
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, 'cis.W001')
        self.assertEqual(errors[0].level, 30)  # WARNING; does not block deploy

    @override_settings(STRIPE_WEBHOOK_SECRET=None)
    def test_unset_secret_warns(self):
        self.assertEqual(len(self._run()), 1)

    @override_settings(STRIPE_WEBHOOK_SECRET='whsec_real_value')
    def test_nonempty_secret_passes(self):
        self.assertEqual(self._run(), [])
