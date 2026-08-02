from django.test import RequestFactory, TestCase

from cis.forms.customuser import MyCELoginForm
from cis.shortcodes import render_shortcodes


class ShortcodeHandlerTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.request = self.rf.get("/")

    def test_breadcrumb_uses_label(self):
        out = render_shortcodes('[breadcrumb label="Student"]', self.request, {})
        self.assertIn("Home", out)
        self.assertIn("Student", out)
        self.assertIn('aria-label="breadcrumb"', out)

    def test_login_form_has_csrf_and_form(self):
        form = MyCELoginForm(self.request)
        out = render_shortcodes("[login_form]", self.request, {"form": form})
        self.assertIn("csrfmiddlewaretoken", out)
        self.assertIn("<form", out)
        self.assertIn("Login", out)

    def test_sso_login_uses_idp_slug(self):
        portal = {"IDP_SLUG": "myslug"}
        out = render_shortcodes('[sso_login label="Go"]', self.request, {"portal": portal})
        self.assertIn("myslug", out)
        self.assertIn("Go", out)

    def test_start_app_open_renders_button(self):
        ctx = {"role": "student", "registration_is_open": True}
        out = render_shortcodes('[start_app label="Start New Application"]', self.request, ctx)
        self.assertIn("Start New Application", out)
        self.assertIn("<a", out)

    def test_start_app_closed_renders_notice(self):
        ctx = {"role": "student", "registration_is_open": False,
               "window_close_notice": "Registration closed"}
        out = render_shortcodes("[start_app]", self.request, ctx)
        self.assertIn("Registration closed", out)
        self.assertNotIn("btn-block btn-primary", out)

    def test_start_app_counselor_always_button(self):
        out = render_shortcodes("[start_app]", self.request, {"role": "counselor"})
        self.assertIn("Submit Access Request", out)

    def test_forgot_password_default_label(self):
        out = render_shortcodes("[forgot_password]", self.request, {})
        self.assertIn("Forgot Password", out)
