"""cis.captcha: one CaptchaField, provider chosen by settings.CAPTCHA_PROVIDER
(ewu#87). Holds for any tenant: each provider's tests skip when its package
is not installed."""
import base64
import importlib.util
import json
import sys
import unittest

from django import forms
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, TestCase, modify_settings, override_settings

from cis import captcha

HAS_ALTCHA = importlib.util.find_spec('django_altcha') is not None
HAS_RECAPTCHA = importlib.util.find_spec('django_recaptcha') is not None


def solved_payload(hmac_key=None):
    """An ALTCHA payload as the browser widget would post it."""
    import altcha
    from django_altcha import get_altcha_challenge

    challenge = get_altcha_challenge(max_number=1000)
    solution = altcha.solve_challenge(
        challenge.challenge, challenge.salt, challenge.algorithm, 1000)
    signature = challenge.signature
    if hmac_key:
        signature = altcha.create_challenge(altcha.ChallengeOptions(
            hmac_key=hmac_key, salt=challenge.salt, number=solution.number,
        )).signature
    return base64.b64encode(json.dumps({
        'algorithm': challenge.algorithm, 'challenge': challenge.challenge,
        'number': solution.number, 'salt': challenge.salt,
        'signature': signature,
    }).encode()).decode()


class ProviderTests(SimpleTestCase):

    @override_settings()
    def test_default_provider_is_recaptcha(self):
        from django.conf import settings
        del settings.CAPTCHA_PROVIDER
        self.assertEqual(captcha.provider(), 'recaptcha')

    @override_settings(CAPTCHA_PROVIDER='altca')
    def test_unknown_provider_is_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured):
            captcha.provider()

    @unittest.skipUnless(HAS_RECAPTCHA, 'django-recaptcha not installed')
    def test_recaptcha_is_the_default_and_does_not_import_altcha(self):
        from django_recaptcha.fields import ReCaptchaField
        was_loaded = 'django_altcha' in sys.modules
        self.assertIs(captcha.build_field_class('recaptcha'), ReCaptchaField)
        if not was_loaded:
            self.assertNotIn('django_altcha', sys.modules)


@unittest.skipUnless(HAS_ALTCHA, 'django-altcha not installed')
# ALTCHA_VERIFICATION_ENABLED is pinned on: a dev/e2e container that sets
# CAPTCHA_TESTING turns verification off, and every rejection below would pass.
@override_settings(ALTCHA_HMAC_KEY='cis-captcha-test-key', ALTCHA_VERIFICATION_ENABLED=True,
                   CACHES={'default': {
                       'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
@modify_settings(INSTALLED_APPS={'append': 'django_altcha'})
class AltchaFieldTests(SimpleTestCase):

    def setUp(self):
        cache.clear()
        self.Field = captcha.build_field_class('altcha')

    def test_accepts_a_solved_challenge(self):
        payload = solved_payload()
        self.assertEqual(self.Field().clean(payload), payload)

    def test_rejects_a_missing_token(self):
        with self.assertRaises(ValidationError):
            self.Field().clean('')

    def test_rejects_a_challenge_signed_with_another_key(self):
        with self.assertRaises(ValidationError):
            self.Field().clean(solved_payload(hmac_key='not-our-key'))

    def test_rejects_garbage(self):
        with self.assertRaises(ValidationError):
            self.Field().clean('bm90IGEgcGF5bG9hZA==')

    def test_rejects_a_replayed_challenge(self):
        payload = solved_payload()
        self.Field().clean(payload)
        with self.assertRaises(ValidationError):
            self.Field().clean(payload)

    def test_has_no_label_and_solves_on_load(self):
        field = self.Field()
        self.assertEqual(field.label, '')
        self.assertEqual(field.widget.options['auto'], 'onload')

    def test_renders_the_self_hosted_widget_and_never_echoes_a_token(self):
        html = self.Field().widget.render('captcha', 'USED-TOKEN')
        self.assertIn('<altcha-widget', html)
        self.assertNotIn('google.com', html)
        self.assertNotIn('USED-TOKEN', html)

    def test_crispy_shows_the_captcha_error(self):
        Field = self.Field

        class CaptchaForm(forms.Form):
            captcha = Field()

        form = CaptchaForm({'captcha': 'eyJ4IjoxfQ=='})
        self.assertFalse(form.is_valid())
        html = Template('{% load crispy_forms_tags %}{{ form|crispy }}').render(
            Context({'form': form}))
        self.assertIn('<altcha-widget', html)
        self.assertIn('We could not verify that you are not a robot.', html)


class CisFormsUseCaptchaFieldTests(TestCase):
    """Every cis form that had reCAPTCHA now uses cis.captcha.CaptchaField."""

    def setUp(self):
        self.request = RequestFactory().get('/', HTTP_HOST='ewu.example.com')
        self.request.user = AnonymousUser()

    def assertUsesCaptcha(self, fields):
        self.assertIsInstance(fields.get('captcha'), captcha.CaptchaField)

    def test_class_level_forms(self):
        from cis.forms.customuser import DemoRequestForm
        from cis.forms.teacher_applicant import NoteReplyForm, TeacherApplicantForm
        for form_class in (DemoRequestForm, NoteReplyForm, TeacherApplicantForm):
            with self.subTest(form=form_class.__name__):
                self.assertUsesCaptcha(form_class.base_fields)

    def test_login_form_off_localhost(self):
        from cis.forms.customuser import MyCELoginForm
        self.assertUsesCaptcha(MyCELoginForm(self.request).fields)

    def test_hs_admin_access_request_form_for_the_public(self):
        from cis.forms.highschool import HSAdminAccessRequestModelForm
        self.assertUsesCaptcha(HSAdminAccessRequestModelForm(request=self.request).fields)

    @override_settings(DEBUG=False)
    def test_password_reset_has_captcha_when_debug_is_off(self):
        from cis.views.password_management import cisPasswordResetForm
        self.assertUsesCaptcha(cisPasswordResetForm(self.request).fields)

    @override_settings(DEBUG=True)
    def test_password_reset_skips_captcha_in_debug(self):
        from cis.views.password_management import cisPasswordResetForm
        self.assertNotIn('captcha', cisPasswordResetForm(self.request).fields)

    def test_no_cis_module_imports_recaptcha_directly(self):
        import pathlib
        root = pathlib.Path(captcha.__file__).parent
        offenders = [
            str(p.relative_to(root)) for p in root.rglob('*.py')
            # build/ is a git-ignored setuptools copy, not cis source.
            if p.name != 'captcha.py' and not {'tests', 'build'} & set(p.relative_to(root).parts)
            and 'django_recaptcha' in p.read_text()
        ]
        self.assertEqual(offenders, [])
