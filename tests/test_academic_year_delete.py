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


class AcademicYearDeleteBulkTests(TestCase):
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
        cls.url = reverse('cis:academic_year_bulk_actions')

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.admin)

    def test_action_registered_bulk_scope(self):
        from myce.component_registry.academic_year import academic_year_actions
        slugs = {slug for g in academic_year_actions.for_scope('bulk', self.admin).values()
                 for slug in g['actions']}
        self.assertIn('delete_academic_years', slugs)

    def test_deletes_selected(self):
        a = AcademicYear.objects.create(name='2023-2024')
        b = AcademicYear.objects.create(name='2024-2025')
        resp = self.client.post(self.url, {'action': 'delete_academic_years',
                                           'ids[]': [str(a.id), str(b.id)]})
        body = resp.json()
        self.assertEqual(body['action'], 'display')
        self.assertEqual(body['status'], 'success')
        self.assertFalse(AcademicYear.objects.filter(pk__in=[a.id, b.id]).exists())

    def test_protected_year_with_terms_not_deleted(self):
        a = AcademicYear.objects.create(name='2025-2026')
        Term.objects.create(academic_year=a, code='25FA', label='Fall')
        resp = self.client.post(self.url, {'action': 'delete_academic_years',
                                           'ids[]': [str(a.id)]})
        body = resp.json()
        self.assertEqual(body['status'], 'warning')
        self.assertTrue(AcademicYear.objects.filter(pk=a.id).exists())

    def test_get_is_rejected_no_deletion(self):
        # Destructive action must not be reachable via GET (CSRF hardening).
        a = AcademicYear.objects.create(name='2026-2027')
        resp = self.client.get(self.url, {'action': 'delete_academic_years',
                                          'ids[]': [str(a.id)]})
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(AcademicYear.objects.filter(pk=a.id).exists())
