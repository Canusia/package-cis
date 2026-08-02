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

SUBTERM_GUID = '11111111-1111-1111-1111-111111111111'
SUBTERM2_GUID = '55555555-5555-5555-5555-555555555555'
PARENT_GUID = '22222222-2222-2222-2222-222222222222'


def _period(guid, code, title, parent_guid, ptype='subterm'):
    return {
        'id': guid, 'code': code, 'title': title,
        'category': {'type': ptype, 'parent': {'id': parent_guid}},
        'startOn': '2024-09-01', 'endOn': '2024-12-15',
    }


class PullSubTermsTests(TestCase):
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
        cls.term = Term.objects.create(
            academic_year=cls.ay, code='24FA', label='Fall',
            external_sis_id=PARENT_GUID)
        cls.url = reverse('cis:term_bulk_actions')

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.admin)

    def test_action_registered_detail_scope(self):
        from myce.component_registry.term import term_actions
        slugs = {slug for g in term_actions.for_scope('detail', self.admin).values()
                 for slug in g['actions']}
        self.assertIn('pull_sub_terms', slugs)

    def test_missing_external_sis_id_errors(self):
        bare = Term.objects.create(academic_year=self.ay, code='24SP', label='Spring')
        resp = self.client.post(self.url, {'action': 'pull_sub_terms',
                                           'ids[]': [str(bare.id)]})
        self.assertEqual(resp.json()['status'], 'error')

    # --- First pass: pull + show selection modal, create nothing ---

    @mock.patch('cis.actions.term.Ethos')
    def test_first_pass_returns_modal_and_creates_nothing(self, MockEthos):
        MockEthos.return_value.get_child_academic_periods.return_value = [
            _period(SUBTERM_GUID, '24FA1', 'Fall A', PARENT_GUID),
        ]
        resp = self.client.post(self.url, {'action': 'pull_sub_terms',
                                           'ids[]': [str(self.term.id)]})
        body = resp.json()
        self.assertEqual(body['outcome'], 'modal')
        self.assertIn('subterm_ids[]', body['html'])
        self.assertIn(SUBTERM_GUID, body['html'])
        self.assertIn('Fall A', body['html'])
        self.assertIn('checked', body['html'])  # default all-checked
        self.assertFalse(Term.objects.filter(external_sis_id=SUBTERM_GUID).exists())

    @mock.patch('cis.actions.term.Ethos')
    def test_first_pass_filters_non_subterm_and_foreign_parent(self, MockEthos):
        MockEthos.return_value.get_child_academic_periods.return_value = [
            _period(SUBTERM_GUID, '24FA1', 'Fall A', PARENT_GUID),
            _period('aaaaaaaa-0000-0000-0000-000000000000', 'X', 'X term',
                    PARENT_GUID, ptype='term'),            # not a subterm
            _period(SUBTERM2_GUID, 'Y', 'Foreign', 'other-guid'),  # foreign parent
        ]
        resp = self.client.post(self.url, {'action': 'pull_sub_terms',
                                           'ids[]': [str(self.term.id)]})
        html = resp.json()['html']
        self.assertIn(SUBTERM_GUID, html)
        self.assertNotIn('X term', html)
        self.assertNotIn('Foreign', html)

    @mock.patch('cis.actions.term.Ethos')
    def test_first_pass_marks_already_linked(self, MockEthos):
        Term.objects.create(academic_year=self.ay, code='24FA1', label='Fall A',
                            parent=self.term, external_sis_id=SUBTERM_GUID)
        MockEthos.return_value.get_child_academic_periods.return_value = [
            _period(SUBTERM_GUID, '24FA1', 'Fall A', PARENT_GUID),
        ]
        resp = self.client.post(self.url, {'action': 'pull_sub_terms',
                                           'ids[]': [str(self.term.id)]})
        self.assertIn('already linked', resp.json()['html'])

    @mock.patch('cis.actions.term.Ethos')
    def test_no_subterms_returns_info_alert(self, MockEthos):
        MockEthos.return_value.get_child_academic_periods.return_value = []
        resp = self.client.post(self.url, {'action': 'pull_sub_terms',
                                           'ids[]': [str(self.term.id)]})
        body = resp.json()
        self.assertEqual(body['outcome'], 'alert')
        self.assertNotEqual(body['status'], 'error')

    # --- Confirm pass: upsert only the selected sub-terms ---

    @mock.patch('cis.actions.term.Ethos')
    def test_confirm_creates_only_selected(self, MockEthos):
        MockEthos.return_value.get_child_academic_periods.return_value = [
            _period(SUBTERM_GUID, '24FA1', 'Fall A', PARENT_GUID),
            _period(SUBTERM2_GUID, '24FA2', 'Fall B', PARENT_GUID),
        ]
        resp = self.client.post(self.url, {
            'action': 'pull_sub_terms', 'action_confirmed': '1',
            'ids[]': [str(self.term.id)],
            'subterm_ids[]': [SUBTERM_GUID],  # only Fall A selected
        })
        self.assertEqual(resp.json()['status'], 'success')
        self.assertTrue(Term.objects.filter(external_sis_id=SUBTERM_GUID).exists())
        self.assertFalse(Term.objects.filter(external_sis_id=SUBTERM2_GUID).exists())
        sub = Term.objects.get(external_sis_id=SUBTERM_GUID)
        self.assertEqual(sub.parent_id, self.term.id)
        self.assertEqual(sub.academic_year_id, self.ay.id)

    @mock.patch('cis.actions.term.Ethos')
    def test_confirm_is_idempotent(self, MockEthos):
        MockEthos.return_value.get_child_academic_periods.return_value = [
            _period(SUBTERM_GUID, '24FA1', 'Fall A', PARENT_GUID),
        ]
        payload = {'action': 'pull_sub_terms', 'action_confirmed': '1',
                   'ids[]': [str(self.term.id)], 'subterm_ids[]': [SUBTERM_GUID]}
        self.client.post(self.url, payload)
        self.client.post(self.url, payload)
        self.assertEqual(Term.objects.filter(external_sis_id=SUBTERM_GUID).count(), 1)

    @mock.patch('cis.actions.term.Ethos')
    def test_confirm_skips_label_collision_with_different_guid(self, MockEthos):
        Term.objects.create(academic_year=self.ay, label='Fall A',
                            external_sis_id='99999999-9999-9999-9999-999999999999')
        MockEthos.return_value.get_child_academic_periods.return_value = [
            _period(SUBTERM_GUID, '24FA1', 'Fall A', PARENT_GUID),
        ]
        self.client.post(self.url, {
            'action': 'pull_sub_terms', 'action_confirmed': '1',
            'ids[]': [str(self.term.id)], 'subterm_ids[]': [SUBTERM_GUID]})
        existing = Term.objects.get(
            label='Fall A', external_sis_id='99999999-9999-9999-9999-999999999999')
        self.assertIsNone(existing.parent_id)
        self.assertFalse(Term.objects.filter(external_sis_id=SUBTERM_GUID).exists())

    @mock.patch('cis.actions.term.Ethos')
    def test_confirm_skips_cycle(self, MockEthos):
        ancestor = Term.objects.create(
            academic_year=self.ay, code='ANC', label='Ancestor',
            external_sis_id='88888888-8888-8888-8888-888888888888')
        self.term.parent = ancestor
        self.term.save()
        MockEthos.return_value.get_child_academic_periods.return_value = [
            _period('88888888-8888-8888-8888-888888888888', 'ANC', 'Ancestor',
                    PARENT_GUID),
        ]
        self.client.post(self.url, {
            'action': 'pull_sub_terms', 'action_confirmed': '1',
            'ids[]': [str(self.term.id)],
            'subterm_ids[]': ['88888888-8888-8888-8888-888888888888']})
        ancestor.refresh_from_db()
        self.assertIsNone(ancestor.parent_id)
