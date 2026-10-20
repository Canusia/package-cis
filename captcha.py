"""
The one captcha field every public form uses, so the provider is decided here.

Opt-in per tenant (ewu#87): ``settings.CAPTCHA_PROVIDER = 'altcha'`` selects
ALTCHA (django-altcha): the browser solves a small proof-of-work puzzle and
the server checks it against ``ALTCHA_HMAC_KEY``, with nothing sent to a
third party. Unset or ``'recaptcha'`` keeps Google reCAPTCHA
(django-recaptcha), unchanged. Only the chosen provider's package is
imported, so an ALTCHA tenant can uninstall django-recaptcha and a reCAPTCHA
tenant need not install django-altcha.

The provider is fixed when this module is imported; override_settings in a
test does not switch ``CaptchaField``. Tests build a class directly with
``build_field_class()``.
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

PROVIDERS = ('recaptcha', 'altcha')


def provider():
    value = getattr(settings, 'CAPTCHA_PROVIDER', 'recaptcha')
    if value not in PROVIDERS:
        raise ImproperlyConfigured(
            f'CAPTCHA_PROVIDER must be one of {PROVIDERS}, not {value!r}.')
    return value


def _altcha_field_class():
    from django_altcha import AltchaField, AltchaWidget

    class CaptchaWidget(AltchaWidget):
        # The ALTCHA widget is a hidden input, and crispy forms renders hidden
        # fields without their errors, so a rejected captcha would fail the
        # form silently. Rendering it as a visible field shows the error.
        is_hidden = False

        def get_context(self, name, value, attrs):
            # A solved challenge is single-use, so never echo the posted one.
            return super().get_context(name, None, attrs)

    class CaptchaField(AltchaField):
        widget = CaptchaWidget

        default_error_messages = {
            'error': 'We could not verify that you are not a robot. Please try again.',
            'invalid': 'We could not verify that you are not a robot. Please try again.',
            'required': 'Please wait for the "Verifying" box to finish, then submit again.',
            'replay': 'This verification was already used. Please submit again.',
        }

        def __init__(self, *args, **kwargs):
            kwargs.setdefault('label', '')
            # Solve as soon as the page loads, so it is usually done before
            # the visitor reaches the submit button.
            kwargs.setdefault('auto', 'onload')
            super().__init__(*args, **kwargs)

    return CaptchaField


def _recaptcha_field_class():
    from django_recaptcha.fields import ReCaptchaField
    return ReCaptchaField


def build_field_class(name):
    return _altcha_field_class() if name == 'altcha' else _recaptcha_field_class()


CaptchaField = build_field_class(provider())
