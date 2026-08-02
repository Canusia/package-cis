from unittest import mock

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models.customuser import CustomUser
from cis.models.term import AcademicYear, Term

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:
    _login_history_post_login = None

PERIOD_GUID = '44444444-4444-4444-4444-444444444444'


class LookupSisIdTests(TestCase):
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
        ce = Group.objects.get_or_create(name='ce')[0]
        cls.admin = CustomUser.objects.create(
            username='ce@x.com', email='ce@x.com', is_active=True)
        cls.admin.set_password('pw')
        cls.admin.save()
        cls.admin.groups.add(ce)
        cls.ay = AcademicYear.objects.create(name='2024-2025')
        cls.term = Term.objects.create(academic_year=cls.ay, code='24/FA', label='Fall')
        cls.url = reverse('cis:term_bulk_actions')

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.admin)

    def test_action_registered_detail_scope(self):
        from myce.component_registry.term import term_actions
        slugs = {slug for g in term_actions.for_scope('detail', self.admin).values()
                 for slug in g['actions']}
        self.assertIn('lookup_sis_id', slugs)

    @mock.patch('cis.actions.term.Ethos')
    def test_lookup_sets_external_sis_id(self, MockEthos):
        MockEthos.return_value.get_academic_period_id.return_value = PERIOD_GUID
        resp = self.client.post(self.url, {'action': 'lookup_sis_id',
                                           'ids[]': [str(self.term.id)]})
        self.assertEqual(resp.json()['status'], 'success')
        MockEthos.return_value.get_academic_period_id.assert_called_once_with('24/FA')
        self.term.refresh_from_db()
        self.assertEqual(str(self.term.external_sis_id), PERIOD_GUID)

    @mock.patch('cis.actions.term.Ethos')
    def test_lookup_not_found_errors_and_leaves_unchanged(self, MockEthos):
        MockEthos.return_value.get_academic_period_id.return_value = None
        resp = self.client.post(self.url, {'action': 'lookup_sis_id',
                                           'ids[]': [str(self.term.id)]})
        self.assertEqual(resp.json()['status'], 'error')
        self.term.refresh_from_db()
        self.assertIsNone(self.term.external_sis_id)
