"""package-cis#111: "See Preview" on the settings overview page.

* The overview page must carry the preview URL and its own (namespaced)
  preview handler, instead of relying on package-setting's global
  ``do_bulk_action`` — which the overview never loaded, and which a tenant
  global of the same name (rvcc's bulk_action.js) can shadow.
* ``highschool_admin_portal.preview()`` must answer for every field its form
  builds (no UnboundLocalError -> 400), and show just the blurb rather than a
  full HS admin page rendered with an empty context.
"""
import json
import re

import importlib.util
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import RequestFactory, TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.settings import Setting
from cis.settings.highschool_admin_portal import highschool_admin_portal

if importlib.util.find_spec('setting.setting'):
    from setting.setting.models import SettingRecord
else:
    from setting.models import SettingRecord

PREVIEW_CALL = re.compile(r"do_bulk_action\('([^']*)', '([^']*)'\)")

HS_MENU = [
    {'type': 'nav-item', 'name': 'home', 'label': 'Home', 'url': 'highschool_admin:dashboard'},
    {'type': 'nav-item', 'name': 'classes', 'label': 'Classes', 'url': 'highschool_admin:classes'},
    {'type': 'nav-item', 'name': 'future_sections', 'label': 'Course Information',
     'url': 'future_sections_highschool_admin:section_requests'},
    {'type': 'nav-item', 'name': 'students', 'label': 'Students', 'url': 'highschool_admin:students'},
    {'type': 'nav-item', 'name': 'tools', 'label': 'Tools', 'sub_menu': [
        {'name': 'student_import', 'label': 'Import Students',
         'url': 'highschool_admin:student_import'},
        {'name': 'bulk_enroll', 'label': 'Bulk Enroll', 'url': 'highschool_admin:bulk_enroll'},
    ]},
    {'type': 'nav-item', 'name': 'drop_wd_requests', 'label': 'Drop/WD Requests',
     'url': 'highschool_admin_drop_wd:requests'},
    {'type': 'nav-item', 'name': 'reports', 'label': 'Reports',
     'url': 'highschool_admin_report:reports'},
    {'type': 'nav-item', 'name': 'logout', 'label': 'Logout', 'url': 'logout'},
]


def _seed_menu():
    Setting.objects.update_or_create(
        key='cis.settings.menu',
        defaults={'value': {'highschool_admin_menu': json.dumps(HS_MENU)}})


def _superuser(username):
    Group.objects.get_or_create(name='ce')
    return CustomUser.objects.create_superuser(
        username=username, email=f'{username}@example.com', password='x')


class HSAdminPortalPreviewTests(TestCase):
    def setUp(self):
        _seed_menu()
        self.user = _superuser('i111prev')
        self.request = RequestFactory().get('/')
        self.request.user = self.user
        self.form = highschool_admin_portal(self.request)

    def test_every_field_has_a_preview_link(self):
        for name, field in self.form.fields.items():
            with self.subTest(field=name):
                match = PREVIEW_CALL.search(str(field.help_text))
                self.assertIsNotNone(match, f'{name} has no See Preview link')
                self.assertEqual(match.groups(), ('highschool_admin_portal', name))

    def test_every_field_previews_its_blurb(self):
        values = {name: f'<p>Text for {name}</p>' for name in self.form.fields}
        Setting.objects.update_or_create(
            key=highschool_admin_portal.key, defaults={'value': values})
        self.assertIn('student_import_blurb', self.form.fields)
        self.assertIn('future_sections_blurb', self.form.fields)
        for name in self.form.fields:
            with self.subTest(field=name):
                resp = self.form.preview(self.request, name)
                self.assertEqual(resp.status_code, 200)
                body = resp.content.decode()
                self.assertIn(values[name], body)
                # The blurb alone, not a whole HS admin page document.
                self.assertNotIn('<html', body.lower())
                self.assertIn(str(self.form.fields[name].label), body)

    def test_unstored_field_previews_placeholder(self):
        Setting.objects.filter(key=highschool_admin_portal.key).delete()
        resp = self.form.preview(self.request, 'students_blurb')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Nothing saved yet', resp.content.decode())

    def test_unknown_field_does_not_raise(self):
        resp = self.form.preview(self.request, 'no_such_page_blurb')
        self.assertEqual(resp.status_code, 200)


class ShowPreviewEndpointTests(TestCase):
    """End to end through package-setting's show_preview, as the link calls it."""

    def setUp(self):
        self._receivers = list(user_logged_in.receivers)
        user_logged_in.receivers = []
        _seed_menu()
        SettingRecord.objects.get_or_create(
            name='highschool_admin_portal', app='cis',
            defaults={'title': 'HS Admin Portal'})
        SettingRecord.objects.get_or_create(
            name='roster_verification', app='cis',
            defaults={'title': 'Roster Verification'})
        self.client.force_login(_superuser('i111ep'))

    def tearDown(self):
        user_logged_in.receivers = self._receivers

    def test_previously_broken_fields_return_200(self):
        Setting.objects.update_or_create(
            key=highschool_admin_portal.key,
            defaults={'value': {'student_import_blurb': '<p>Import help</p>'}})
        for field in ('classes_blurb', 'future_sections_blurb', 'students_blurb',
                      'student_import_blurb', 'bulk_enroll_blurb', 'drop_wd_requests_blurb',
                      'reports_blurb', 'side_bar_blurb', 'student_blurb'):
            with self.subTest(field=field):
                resp = self.client.get(reverse('setting:show_preview'), {
                    'setting': 'highschool_admin_portal', 'field': field})
                self.assertEqual(resp.status_code, 200, resp.content[:200])
        resp = self.client.get(reverse('setting:show_preview'), {
            'setting': 'highschool_admin_portal', 'field': 'student_import_blurb'})
        self.assertIn(b'<p>Import help</p>', resp.content)

    def test_roster_verification_intro_previews_blurb(self):
        from cis.settings.roster_verification import roster_verification
        Setting.objects.update_or_create(
            key=roster_verification.key, defaults={'value': {'intro': '<p>Verify me</p>'}})
        resp = self.client.get(reverse('setting:show_preview'), {
            'setting': 'roster_verification', 'field': 'intro'})
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        self.assertIn(b'<p>Verify me</p>', resp.content)


class OverviewPagePreviewWiringTests(TestCase):
    def setUp(self):
        self._receivers = list(user_logged_in.receivers)
        user_logged_in.receivers = []
        Group.objects.get_or_create(name='student')
        self.client.force_login(_superuser('i111ov'))

    def tearDown(self):
        user_logged_in.receivers = self._receivers

    def _page(self):
        url = reverse('cis:settings_overview', kwargs={'profile': 'student_registration'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_page_carries_preview_url(self):
        body = self._page()
        self.assertIn(f'data-url-show-preview="{reverse("setting:show_preview")}"', body)

    def test_page_defines_namespaced_preview_handler(self):
        body = self._page()
        self.assertIn('cisSettingsOverview', body)
        self.assertIn('showPreview', body)
        # Inline do_bulk_action(...) calls in injected forms are rewired to
        # the namespaced handler rather than resolved against a global.
        self.assertIn('rewirePreviewLinks', body)
        self.assertNotIn('function do_bulk_action', body)
