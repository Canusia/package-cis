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

    def test_falls_back_to_default_when_unset(self):
        # No portal_content setting saved in the test DB -> uses DEFAULT_BODIES.
        out = render_landing_body(self.request, "student", {"registration_is_open": True})
        self.assertIn("breadcrumb", out)  # breadcrumb partial rendered
        self.assertIn("Start New Application", out)

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
