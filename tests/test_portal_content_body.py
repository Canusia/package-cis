from django.test import RequestFactory, TestCase

from cis.landing_content import DEFAULT_BODIES
from cis.settings.portal_content import portal_content


class PortalContentBodyTests(TestCase):
    def test_form_has_body_fields(self):
        form = portal_content(RequestFactory().get("/"))
        for role in ["student", "instructor", "faculty", "staff", "counselor"]:
            self.assertIn(f"{role}_body", form.fields)

    def test_install_seeds_bodies_from_defaults(self):
        portal_content(RequestFactory().get("/")).install()
        stored = portal_content.from_db()
        for role, default in DEFAULT_BODIES.items():
            self.assertEqual(stored.get(f"{role}_body"), default)
