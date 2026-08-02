import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase, RequestFactory

from cis.models.customuser import CustomUser
from cis.models.settings import Setting
from cis.models.student import Student, StudentSupportingDocument
from cis.models.term import AcademicYear, Term
from cis.settings.support_docs import support_docs

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:
    _login_history_post_login = None


def _user(**overrides):
    defaults = {
        'username': f'u-{uuid.uuid4()}',
        'email': f'{uuid.uuid4()}@example.com',
        'first_name': 'Test', 'last_name': 'User', 'psid': '-',
    }
    defaults.update(overrides)
    return CustomUser.objects.create(**defaults)


def _set_support_docs(**overrides):
    value = {
        'types': [], 'statuses': [], 'email_enabled': 'No',
        'status_change_email_subject': '', 'status_change_email': '',
    }
    value.update(overrides)
    Setting.objects.update_or_create(key=support_docs.key, defaults={'value': value})


class SupportDocsSettingTests(TestCase):
    def _request(self):
        return RequestFactory().get('/?report_id=x')

    def test_merged_form_round_trip(self):
        form = support_docs(self._request(), data={
            'types': 'Transcript\n\n  Waiver ',
            'statuses': 'Pending\nApproved',
            'email_enabled': 'Yes',
            'status_change_email_subject': 'Status update',
            'status_change_email': 'Hi {{student_first_name}}',
        })
        self.assertTrue(form.is_valid(), form.errors.as_json())
        form.run_record()
        self.assertEqual(support_docs.get_types(), ['Transcript', 'Waiver'])
        self.assertEqual(support_docs.get_statuses(), ['Pending', 'Approved'])
        cfg = support_docs.get_config()
        self.assertEqual(cfg['email_enabled'], 'Yes')
        self.assertEqual(cfg['status_change_email_subject'], 'Status update')
        # from_db renders lists back into their textareas.
        self.assertEqual(support_docs.from_db()['types'], 'Transcript\nWaiver')

    def test_getters_empty_when_unset(self):
        Setting.objects.filter(key=support_docs.key).delete()
        self.assertEqual(support_docs.get_types(), [])
        self.assertEqual(support_docs.get_statuses(), [])
        self.assertEqual(support_docs.get_config(), {})


class UploadFormDocumentTypeTests(TestCase):
    def test_document_type_choices_from_setting_and_status_excluded(self):
        from cis.forms.student import StudentSupportingDocumentForm
        _set_support_docs(types=['Transcript', 'Waiver'])
        form = StudentSupportingDocumentForm(SimpleNamespace(id=uuid.uuid4()))
        labels = [c[1] for c in form.fields['document_type'].choices]
        self.assertEqual(labels, ['Select type', 'Transcript', 'Waiver'])
        self.assertNotIn('status', form.fields)


class MarkSupportDocStatusBulkActionTests(TestCase):
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
        Group.objects.get_or_create(name='ce')
        Group.objects.get_or_create(name='student')
        cls.admin = _user(username='ce@x.com', email='ce@x.com')
        cls.admin.groups.add(Group.objects.get(name='ce'))

        ay = AcademicYear.objects.create(name='AY-2099')
        cls.term = Term.objects.create(academic_year=ay, code='209901', label='Fall')
        cls.student = Student.objects.create(user=_user())
        cls.d1 = StudentSupportingDocument.objects.create(
            student=cls.student, term=cls.term, media='docs/a.pdf')
        cls.d2 = StudentSupportingDocument.objects.create(
            student=cls.student, term=cls.term, media='docs/b.pdf')
        cls.url = '/ce/students/support_docs/bulk_actions'

    def setUp(self):
        _set_support_docs(statuses=['Pending', 'Approved'])
        self.client.force_login(self.admin)

    def test_files_tab_includes_bulk_actions(self):
        from cis.tabs.student import files_tab
        req = RequestFactory().get('/')
        req.user = self.admin
        cfg = files_tab(req, self.student)['support_docs_table']
        self.assertIsNotNone(cfg['bulk_actions'])
        slugs = {s for g in cfg['bulk_actions'].values() for s in g['actions']}
        self.assertIn('mark_support_doc_status', slugs)

    def test_support_docs_page_renders_bulk_action_button(self):
        resp = self.client.get('/ce/students/support_docs/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('Mark Status', html)
        self.assertIn('mark_support_doc_status', html)

    def test_first_pass_returns_modal_with_status_dropdown(self):
        resp = self.client.post(self.url, {
            'action': 'mark_support_doc_status',
            'ids[]': [str(self.d1.id), str(self.d2.id)],
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['outcome'], 'modal')
        self.assertIn('name="status"', body['html'])
        self.assertIn('Approved', body['html'])

    def test_confirm_pass_updates_status(self):
        resp = self.client.post(self.url, {
            'action': 'mark_support_doc_status',
            'action_confirmed': '1',
            'record_ids': [str(self.d1.id), str(self.d2.id)],
            'status': 'Approved',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['outcome'], 'call')
        self.d1.refresh_from_db()
        self.d2.refresh_from_db()
        self.assertEqual(self.d1.status, 'Approved')
        self.assertEqual(self.d2.status, 'Approved')

    def test_confirm_rejects_status_not_in_setting(self):
        resp = self.client.post(self.url, {
            'action': 'mark_support_doc_status',
            'action_confirmed': '1',
            'record_ids': [str(self.d1.id)],
            'status': 'Bogus',
        })
        self.assertEqual(resp.status_code, 400)
        self.d1.refresh_from_db()
        self.assertEqual(self.d1.status, '')


class StatusChangeEmailSignalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        ay = AcademicYear.objects.create(name='AY-2099')
        cls.term = Term.objects.create(academic_year=ay, code='209901', label='Fall')
        cls.student = Student.objects.create(user=_user(first_name='Ada'))

    def _doc(self, **kw):
        return StudentSupportingDocument.objects.create(
            student=self.student, term=self.term, media='docs/x.pdf', **kw)

    def test_email_sent_on_status_change_when_enabled(self):
        _set_support_docs(
            statuses=['Pending', 'Approved'], email_enabled='Yes',
            status_change_email_subject='Status update',
            status_change_email='Hi {{student_first_name}}, status is {{status}}.')
        doc = self._doc(status='Pending')
        with patch('cis.signals.support_docs.send_html_mail') as mock_send:
            doc.status = 'Approved'
            doc.save()
        self.assertTrue(mock_send.called)
        subject, text_body = mock_send.call_args[0][0], mock_send.call_args[0][1]
        self.assertEqual(subject, 'Status update')
        self.assertIn('status is Approved', text_body)

    def test_no_email_when_disabled(self):
        _set_support_docs(email_enabled='No')
        doc = self._doc(status='Pending')
        with patch('cis.signals.support_docs.send_html_mail') as mock_send:
            doc.status = 'Approved'
            doc.save()
        self.assertFalse(mock_send.called)

    def test_no_email_when_status_unchanged(self):
        _set_support_docs(email_enabled='Yes', status_change_email='x')
        doc = self._doc(status='Pending')
        with patch('cis.signals.support_docs.send_html_mail') as mock_send:
            doc.description = 'edited note'
            doc.save()
        self.assertFalse(mock_send.called)

    def test_no_email_on_create(self):
        _set_support_docs(email_enabled='Yes', status_change_email='x')
        with patch('cis.signals.support_docs.send_html_mail') as mock_send:
            self._doc(status='Pending')
        self.assertFalse(mock_send.called)
