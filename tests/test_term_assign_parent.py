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


class AssignParentTermTests(TestCase):
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
        cls.parent = Term.objects.create(academic_year=cls.ay, code='24', label='Year')
        cls.a = Term.objects.create(academic_year=cls.ay, code='24FA', label='Fall')
        cls.b = Term.objects.create(academic_year=cls.ay, code='24SP', label='Spring')
        cls.url = reverse('cis:term_bulk_actions')

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.admin)

    def test_action_registered(self):
        from myce.component_registry.term import term_actions
        slugs = {slug for g in term_actions.for_scope('index', self.admin).values()
                 for slug in g['actions']}
        self.assertIn('assign_parent', slugs)

    def test_first_pass_returns_modal_with_parent_select(self):
        resp = self.client.post(self.url, {'action': 'assign_parent',
                                           'ids[]': [str(self.a.id), str(self.b.id)]})
        body = resp.json()
        self.assertEqual(body['outcome'], 'modal')
        self.assertIn('name="parent"', body['html'])
        # candidate parent must exclude the selected rows
        self.assertIn(str(self.parent.id), body['html'])
        self.assertNotIn(str(self.a.id), body['html'].split('name="parent"')[1])

    def test_confirm_assigns_parent(self):
        resp = self.client.post(self.url, {
            'action': 'assign_parent', 'action_confirmed': '1',
            'ids[]': [str(self.a.id), str(self.b.id)],
            'parent': str(self.parent.id),
        })
        self.assertEqual(resp.json()['outcome'], 'call')
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.parent_id, self.parent.id)
        self.assertEqual(self.b.parent_id, self.parent.id)

    def test_confirm_skips_self_and_cycle(self):
        # b is a child of a; assigning parent=b to {a, parent} must skip a (cycle)
        self.b.parent = self.a
        self.b.save()
        resp = self.client.post(self.url, {
            'action': 'assign_parent', 'action_confirmed': '1',
            'ids[]': [str(self.a.id), str(self.parent.id)],
            'parent': str(self.b.id),
        })
        self.assertEqual(resp.json()['outcome'], 'call')
        self.a.refresh_from_db(); self.parent.refresh_from_db()
        self.assertIsNone(self.a.parent_id)          # skipped (cycle: b descends from a)
        self.assertEqual(self.parent.parent_id, self.b.id)  # assigned

    def test_confirm_requires_parent(self):
        resp = self.client.post(self.url, {
            'action': 'assign_parent', 'action_confirmed': '1',
            'ids[]': [str(self.a.id)],
        })
        self.assertEqual(resp.status_code, 400)
        self.a.refresh_from_db()
        self.assertIsNone(self.a.parent_id)

    def test_delete_terms_returns_call_and_deletes(self):
        term1 = Term.objects.create(academic_year=self.ay, code='25FA', label='Fall 25')
        term2 = Term.objects.create(academic_year=self.ay, code='25SP', label='Spring 25')
        resp = self.client.post(self.url, {
            'action': 'delete_terms',
            'ids[]': [str(term1.id), str(term2.id)],
        })
        body = resp.json()
        self.assertEqual(body['outcome'], 'call')
        self.assertEqual(body['fn'], 'onBulkActionComplete')
        self.assertEqual(
            Term.objects.filter(pk__in=[term1.id, term2.id]).count(), 0)
