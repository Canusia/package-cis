from django.test import RequestFactory, TestCase

from cis.landing_content import DEFAULT_BODIES, render_landing_body


class LandingBodyTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/")

    def test_default_bodies_cover_all_roles(self):
        self.assertEqual(
            set(DEFAULT_BODIES),
            {"student", "instructor", "faculty", "staff", "counselor"},
        )

    # test_falls_back_to_default_when_unset moved to the tenant repo
    # (myce_tenant_configs/tests/test_landing_body_tenant.py, ewu#34): it
    # asserted the student default body offers password signup, which is false
    # on a tenant whose students sign in through SSO only.

    def test_custom_body_from_setting_is_used(self):
        from cis.models.settings import Setting
        from cis.settings.portal_content import portal_content
        Setting.objects.update_or_create(
            key=portal_content.key,
            defaults={"value": {"student_body": "<p>CUSTOM</p>[breadcrumb label=\"S\"]"}},
        )
        out = render_landing_body(self.request, "student", {})
        self.assertIn("CUSTOM", out)
        self.assertIn("aria-label=\"breadcrumb\"", out)
