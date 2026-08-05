from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:
    _login_history_post_login = None


class LandingPagesShortcodeTests(TestCase):
    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    # test_student_page_renders_body_from_shortcodes moved to the tenant repo
    # (myce_tenant_configs/tests/test_landing_body_tenant.py, ewu#34): it
    # asserted [login_form] expands on the student landing page, which is a
    # statement about how that tenant's students sign in, not about shortcode
    # expansion. The other portals below stay — none of them assume a
    # particular signup mechanic.

    def test_student_custom_body_setting_overrides(self):
        from cis.models.settings import Setting
        from cis.settings.portal_content import portal_content
        Setting.objects.update_or_create(
            key=portal_content.key,
            defaults={"value": {"student_body": "<div id=\"custom-marker\">hi</div>"}},
        )
        resp = self.client.get(reverse("student_index"))
        self.assertIn('id="custom-marker"', resp.content.decode())

    def test_instructor_page_renders_body(self):
        resp = self.client.get(reverse("instructor_index"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('aria-label="breadcrumb"', html)
        self.assertNotIn("[breadcrumb", html)

    def test_faculty_page_renders_sso_body(self):
        resp = self.client.get(reverse("faculty_index"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('aria-label="breadcrumb"', html)
        self.assertNotIn("[sso_login", html)
        self.assertIn("Login Now", html)

    def test_staff_page_renders_sso_body(self):
        resp = self.client.get(reverse("staff_index"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertNotIn("[sso_login", html)
        self.assertIn("Login Now", resp.content.decode())

    def test_highschool_admin_page_renders_body(self):
        resp = self.client.get(reverse("highschool_admin_index"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Submit Access Request", html)     # [start_app] counselor
        self.assertNotIn("[login_form]", html)

    def test_instructor_custom_body_overrides(self):
        from cis.models.settings import Setting
        from cis.settings.portal_content import portal_content
        Setting.objects.update_or_create(
            key=portal_content.key,
            defaults={"value": {"instructor_body": '<div id="inst-marker">hi</div>'}},
        )
        resp = self.client.get(reverse("instructor_index"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="inst-marker"', resp.content.decode())

    def test_faculty_custom_body_overrides(self):
        from cis.models.settings import Setting
        from cis.settings.portal_content import portal_content
        Setting.objects.update_or_create(
            key=portal_content.key,
            defaults={"value": {"faculty_body": '<div id="fac-marker">hi</div>'}},
        )
        resp = self.client.get(reverse("faculty_index"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="fac-marker"', resp.content.decode())

    def test_staff_custom_body_overrides(self):
        from cis.models.settings import Setting
        from cis.settings.portal_content import portal_content
        Setting.objects.update_or_create(
            key=portal_content.key,
            defaults={"value": {"staff_body": '<div id="staff-marker">hi</div>'}},
        )
        resp = self.client.get(reverse("staff_index"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="staff-marker"', resp.content.decode())

    def test_counselor_custom_body_overrides(self):
        from cis.models.settings import Setting
        from cis.settings.portal_content import portal_content
        Setting.objects.update_or_create(
            key=portal_content.key,
            defaults={"value": {"counselor_body": '<div id="couns-marker">hi</div>'}},
        )
        resp = self.client.get(reverse("highschool_admin_index"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="couns-marker"', resp.content.decode())

    def test_facilitator_breadcrumb_shows_facilitator_label(self):
        resp = self.client.get(reverse("highschool_facilitator_index"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Facilitator", html)
        self.assertNotIn("School Counselor or Administrator", html)

    def test_highschool_admin_breadcrumb_shows_admin_label(self):
        resp = self.client.get(reverse("highschool_admin_index"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("School Counselor or Administrator", resp.content.decode())
