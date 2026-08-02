"""PT-31: the Stripe webhook must fail closed when STRIPE_WEBHOOK_SECRET is
empty/unset (never reach signature verification or business logic), and a
system check must require a non-empty secret.
"""
import json

from django.test import TestCase, override_settings
from django.urls import reverse

from student_transactions.models import StudentTransaction


FORGED_EVENT = json.dumps({
    'id': 'evt_test_checkout_1',
    'object': 'event',
    'type': 'payment_intent.succeeded',
    'data': {'object': {'id': 'pi_test_123', 'object': 'payment_intent',
                        'amount_received': 5000, 'metadata': {}}},
}, separators=(',', ':'))


class StripeWebhookFailClosedTests(TestCase):
    def setUp(self):
        self.url = reverse('stripe_webhook')  # /webhooks/stripe/

    @override_settings(STRIPE_WEBHOOK_SECRET='')
    def test_empty_secret_fails_closed_500_and_no_processing(self):
        before = StudentTransaction.objects.count()
        resp = self.client.post(
            self.url, data=FORGED_EVENT, content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=1,v1=deadbeef')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(StudentTransaction.objects.count(), before)

    @override_settings(STRIPE_WEBHOOK_SECRET=None)
    def test_unset_secret_fails_closed_500(self):
        resp = self.client.post(
            self.url, data=FORGED_EVENT, content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=1,v1=deadbeef')
        self.assertEqual(resp.status_code, 500)

    @override_settings(STRIPE_WEBHOOK_SECRET='whsec_unit_test_secret')
    def test_nonempty_secret_with_bad_signature_is_rejected_400(self):
        resp = self.client.post(
            self.url, data=FORGED_EVENT, content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=1,v1=deadbeef')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(StudentTransaction.objects.count(), 0)


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
