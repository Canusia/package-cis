"""All /ce/settings/ endpoints must be CE-only (PT-13, and the PT-2/PT-3 XSS
injection vector). A highschool_admin is blocked (403 for JSON, redirect for
HTML pages); a CE admin is admitted. The {{...|safe}} rendering is intentionally
left unchanged — this is an access-control fix only.
"""
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.settings import Setting
from cis.settings.instructor_portal import instructor_portal
from cis.settings.signup import signup

try:
    from setting.setting.models.setting import SettingRecord
except Exception:  # pragma: no cover
    from setting.models.setting import SettingRecord

User = get_user_model()

XSS_IMG = '<img src=x onerror="console.log(\'AIKIDO_CANARY\')">'


class SettingsCeOnlyTests(TestCase):
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

    @classmethod
    def setUpTestData(cls):
        for name in ('ce', 'highschool_admin'):
            Group.objects.get_or_create(name=name)

        ce = User.objects.create_user(
            username='ce_set', email='ce_set@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce

        hsa = User.objects.create_user(
            username='hsa_set', email='hsa_set@example.com', password='x',
            first_name='Hank', last_name='Admin',
        )
        hsa.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa

        # Real records so run_record targets the genuine PT-2/PT-3 exploit path.
        cls.pt2_record = SettingRecord.objects.create(
            app='cis', name='instructor_portal',
            title='Portal - Instructor Pages', categories='4',
        )
        cls.pt3_record = SettingRecord.objects.create(
            app='cis', name='signup',
            title='Student Portal - New Student Signup Page Template',
            categories='1',
        )

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')

    # ---- JSON endpoints: highschool_admin must get 403 ---------------------
    def test_hsadmin_403_records_in_category(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(
            reverse('setting:records_in_category'), {'category': '4'})
        self.assertEqual(resp.status_code, 403)

    def test_hsadmin_403_record_details(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(
            reverse('setting:record_details'),
            {'report_id': str(self.pt2_record.id)})
        self.assertEqual(resp.status_code, 403)

    def test_hsadmin_403_show_preview(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(
            reverse('setting:show_preview'),
            {'setting': 'cis.instructor_portal', 'field': 'classes_blurb'})
        self.assertEqual(resp.status_code, 403)

    def test_hsadmin_403_run_record(self):
        self.client.force_login(self.hsadmin_user)
        url = reverse('setting:run_record',
                      kwargs={'record_id': self.pt2_record.id})
        resp = self.client.post(url, {'classes_blurb': 'ok'})
        self.assertEqual(resp.status_code, 403)

    def test_hsadmin_403_update_setting(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.post(
            reverse('setting:update_setting'),
            {'record_id': str(self.pt2_record.id), 'title': 'x'})
        self.assertEqual(resp.status_code, 403)

    # ---- HTML pages: highschool_admin must be redirected away --------------
    def test_hsadmin_redirected_from_records_index(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(reverse('setting:records'))
        self.assertEqual(resp.status_code, 302)

    def test_hsadmin_redirected_from_add_new(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(reverse('setting:add_new'))
        self.assertEqual(resp.status_code, 302)

    # ---- PT-2 / PT-3: payload cannot be stored by a non-CE role ------------
    def test_hsadmin_cannot_store_pt2_payload(self):
        self.client.force_login(self.hsadmin_user)
        url = reverse('setting:run_record',
                      kwargs={'record_id': self.pt2_record.id})
        resp = self.client.post(url, {'classes_blurb': XSS_IMG})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(
            Setting.objects.filter(key=instructor_portal.key).exists())

    def test_hsadmin_cannot_store_pt3_payload(self):
        self.client.force_login(self.hsadmin_user)
        url = reverse('setting:run_record',
                      kwargs={'record_id': self.pt3_record.id})
        resp = self.client.post(url, {'awaiting_verify_intro': XSS_IMG})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Setting.objects.filter(key=signup.key).exists())

    # ---- CE admin is admitted everywhere -----------------------------------
    def test_ce_admitted_records_in_category(self):
        self.client.force_login(self.ce_user)
        resp = self.client.get(
            reverse('setting:records_in_category'), {'category': '4'})
        self.assertEqual(resp.status_code, 200)

    def test_ce_admitted_records_index(self):
        self.client.force_login(self.ce_user)
        resp = self.client.get(reverse('setting:records'))
        self.assertEqual(resp.status_code, 200)

    def test_ce_admitted_run_record(self):
        self.client.force_login(self.ce_user)
        url = reverse('setting:run_record',
                      kwargs={'record_id': self.pt2_record.id})
        resp = self.client.post(url, {'classes_blurb': 'Welcome to classes.'})
        # Past the CE gate (not 403); form may 400 on other required fields.
        self.assertNotEqual(resp.status_code, 403)
