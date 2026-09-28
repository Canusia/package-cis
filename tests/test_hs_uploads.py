"""#56: high-school uploads -- term + review tracking and the CE review tab.

HighSchoolTranscript gains term / reviewed_on / reviewed_by, and uploaded_on
becomes auto_now_add so reviewing a file cannot move its upload date. CE sees
every school's uploads on a "High School Uploads" tab of
/ce/students/support_docs/ and marks them reviewed through cis.actions.hs_uploads.
The upload form validates type and size against the hs_uploads setting, and
an HS-admin upload emails that setting's notify list.
"""
import importlib
import json
import uuid
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool, HighSchoolTranscript
from cis.models.settings import Setting
from cis.models.term import AcademicYear, Term
from cis.settings.hs_uploads import hs_uploads

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None


def _sfx():
    return uuid.uuid4().hex[:8]


def _file(name='building.pdf', size=10):
    return SimpleUploadedFile(name, b'x' * size, content_type='application/octet-stream')


def _set(**value):
    Setting.objects.update_or_create(key=hs_uploads.key, defaults={'value': value})


class _Base(TestCase):
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

    def setUp(self):
        patcher = mock.patch(
            'cis.storage_backend.PrivateMediaStorage._save',
            side_effect=lambda name, content: name)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.ce = CustomUser.objects.create_user(
            username=f'ce{_sfx()}', email=f'ce{_sfx()}@x.com', password='x',
            first_name='Cora', last_name='Staff')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.hsadmin = CustomUser.objects.create_user(
            username=f'hs{_sfx()}', email=f'hs{_sfx()}@x.com', password='x',
            first_name='Hal', last_name='Admin')
        self.hsadmin.groups.add(Group.objects.get_or_create(name='highschool_admin')[0])

        ay = AcademicYear.objects.create(name=f'AY{_sfx()}')
        self.fall = Term.objects.create(academic_year=ay, code=f'F{_sfx()}', label='Fall')
        self.spring = Term.objects.create(academic_year=ay, code=f'S{_sfx()}', label='Spring')
        self.hs_a = HighSchool.objects.create(name=f'Auburn {_sfx()}', status='Active')
        self.hs_b = HighSchool.objects.create(name=f'Bristol {_sfx()}', status='Active')

    def upload(self, highschool, term=None, by=None, description='Files'):
        return HighSchoolTranscript.objects.create(
            highschool=highschool, term=term, uploaded_by=by or self.hsadmin,
            description=description, media=_file())


class ReviewTrackingTests(_Base):
    def test_marking_reviewed_keeps_the_upload_date(self):
        record = self.upload(self.hs_a, self.fall)
        uploaded_on = record.uploaded_on

        record.mark_reviewed(self.ce)
        record.refresh_from_db()

        self.assertEqual(record.uploaded_on, uploaded_on)
        self.assertEqual(record.reviewed_by, self.ce)
        self.assertIsNotNone(record.reviewed_on)
        self.assertTrue(record.is_reviewed)

    def test_mark_not_reviewed_clears_both_fields(self):
        record = self.upload(self.hs_a)
        record.mark_reviewed(self.ce)
        record.mark_not_reviewed()
        record.refresh_from_db()
        self.assertIsNone(record.reviewed_on)
        self.assertIsNone(record.reviewed_by)
        self.assertFalse(record.is_reviewed)


class UploadFormTests(_Base):
    def _form(self, **overrides):
        from cis.forms.highschool import HSTranscriptUploadForm
        data = {'description': 'Auburn transcripts', 'term': str(self.fall.id)}
        files = {'media': overrides.pop('media', _file())}
        data.update(overrides)
        return HSTranscriptUploadForm(data, files)

    def test_allowed_type_passes(self):
        with mock.patch('cis.forms.highschool.upload_terms',
                        return_value=Term.objects.all()):
            form = self._form()
            self.assertTrue(form.is_valid(), form.errors)

    def test_disallowed_type_is_rejected(self):
        with mock.patch('cis.forms.highschool.upload_terms',
                        return_value=Term.objects.all()):
            form = self._form(media=_file('script.exe'))
            self.assertFalse(form.is_valid())
            self.assertIn('media', form.errors)

    def test_file_over_the_size_limit_is_rejected(self):
        _set(max_upload_mb=1)
        with mock.patch('cis.forms.highschool.upload_terms',
                        return_value=Term.objects.all()):
            form = self._form(media=_file(size=1024 * 1024 + 1))
            self.assertFalse(form.is_valid())
            self.assertIn('media', form.errors)

    def test_description_is_required(self):
        with mock.patch('cis.forms.highschool.upload_terms',
                        return_value=Term.objects.all()):
            form = self._form(description='')
            self.assertFalse(form.is_valid())
            self.assertIn('description', form.errors)

    def test_term_limited_to_active_and_registration_terms(self):
        from cis.forms import highschool as forms_module
        with mock.patch('cis.utils.active_term', return_value=self.fall), \
                mock.patch('cis.utils.registration_terms', return_value=None):
            self.assertEqual(list(forms_module.upload_terms()), [self.fall])

    def test_settings_defaults(self):
        Setting.objects.filter(key=hs_uploads.key).delete()
        self.assertEqual(hs_uploads.allowed_extensions(),
                         ['pdf', 'xlsx', 'csv', 'jpg', 'png'])
        self.assertEqual(hs_uploads.max_upload_bytes(), 100 * 1024 * 1024)
        self.assertEqual(hs_uploads.notify_recipients(), [])


class UploadsApiTests(_Base):
    URL = '/ce/api/highschool-transcript/'

    def setUp(self):
        super().setUp()
        self.fall_a = self.upload(self.hs_a, self.fall)
        self.spring_b = self.upload(self.hs_b, self.spring)
        self.spring_b.mark_reviewed(self.ce)
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    def _ids(self, **params):
        self.client.force_login(self.ce)
        resp = self.client.get(self.URL, {'format': 'json', **params})
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        body = resp.json()
        rows = body['results'] if isinstance(body, dict) else body
        return {row['id'] for row in rows}

    def test_lists_every_school_without_highschool_id(self):
        self.assertEqual(self._ids(), {str(self.fall_a.id), str(self.spring_b.id)})

    def test_filters(self):
        self.assertEqual(self._ids(highschool_id=str(self.hs_a.id)), {str(self.fall_a.id)})
        self.assertEqual(self._ids(term=str(self.spring.id)), {str(self.spring_b.id)})
        self.assertEqual(self._ids(reviewed='yes'), {str(self.spring_b.id)})
        self.assertEqual(self._ids(reviewed='no'), {str(self.fall_a.id)})

    def test_invalid_uuid_returns_empty_not_500(self):
        self.assertEqual(self._ids(highschool_id='not-a-uuid'), set())
        self.assertEqual(self._ids(term='nope'), set())

    def test_serializer_carries_term_and_review(self):
        self.client.force_login(self.ce)
        resp = self.client.get(self.URL, {'format': 'json', 'reviewed': 'yes'})
        body = resp.json()
        row = (body['results'] if isinstance(body, dict) else body)[0]
        self.assertEqual(row['term']['label'], 'Spring')
        self.assertTrue(row['reviewed_on'])
        self.assertEqual(row['reviewed_by']['last_name'], 'Staff')

    def test_non_ce_refused(self):
        self.client.force_login(self.hsadmin)
        resp = self.client.get(self.URL, {'format': 'json'})
        self.assertIn(resp.status_code, (401, 403))


class ReviewActionTests(_Base):
    def setUp(self):
        super().setUp()
        self.record = self.upload(self.hs_a, self.fall)
        self.url = reverse('cis:hs_uploads_bulk_action')

    def _post(self, user, action, ids=None, method='post'):
        self.client.force_login(user)
        return getattr(self.client, method)(
            self.url, {'action': action, 'ids[]': ids or [str(self.record.id)]})

    def test_unknown_action_400_before_method_check(self):
        self.assertEqual(self._post(self.ce, 'nope', method='get').status_code, 400)

    def test_get_is_refused(self):
        resp = self._post(self.ce, 'mark_hs_uploads_reviewed', method='get')
        self.assertEqual(resp.status_code, 405)
        self.record.refresh_from_db()
        self.assertFalse(self.record.is_reviewed)

    def test_mark_reviewed_and_undo(self):
        resp = self._post(self.ce, 'mark_hs_uploads_reviewed')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['outcome'], 'call')
        self.record.refresh_from_db()
        self.assertEqual(self.record.reviewed_by, self.ce)

        self._post(self.ce, 'mark_hs_uploads_not_reviewed')
        self.record.refresh_from_db()
        self.assertFalse(self.record.is_reviewed)

    def test_invalid_ids_are_skipped(self):
        resp = self._post(self.ce, 'mark_hs_uploads_reviewed', ids=['junk', str(uuid.uuid4())])
        self.assertEqual(resp.status_code, 200)
        self.assertIn('0 upload', resp.json()['args']['message'])

    def test_non_ce_refused(self):
        resp = self._post(self.hsadmin, 'mark_hs_uploads_reviewed')
        self.assertNotEqual(resp.status_code, 200)
        self.record.refresh_from_db()
        self.assertFalse(self.record.is_reviewed)


class SupportDocsTabTests(_Base):
    def setUp(self):
        super().setUp()
        self.upload(self.hs_a, self.fall, description='Auburn building PDF')
        self.client.force_login(self.ce)

    def test_tab_renders(self):
        resp = self.client.get(reverse('cis:support_docs'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('href="#hs_uploads"', html)
        self.assertIn('id="hs_uploads"', html)

    def test_tab_renders_without_the_table_module(self):
        with mock.patch('cis.views.hs_uploads.get_table_config',
                        side_effect=ImportError('no hs_uploads_table')):
            resp = self.client.get(reverse('cis:support_docs'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Auburn building PDF')


class NotifyTests(_Base):
    def _queued(self):
        from mailer.models import Message
        return list(Message.objects.all())

    def test_emails_the_notify_list(self):
        _set(notify_emails='office@x.com, dean@x.com',
             notify_subject='New upload from {{highschool}}',
             notify_email='{{uploaded_by}} uploaded {{file_name}} for {{term}}: {{description}}')
        from cis.services.hs_uploads import notify_hs_upload
        record = self.upload(self.hs_a, self.fall, description='All fall students')

        sent = notify_hs_upload(record)

        self.assertEqual(sent, ['office@x.com', 'dean@x.com'])
        messages = self._queued()
        self.assertEqual(len(messages), 1)
        email = messages[0].email
        self.assertIn(self.hs_a.name, email.subject)
        self.assertIn('All fall students', email.body)
        self.assertIn('Hal Admin', email.body)

    def test_blank_notify_list_sends_nothing(self):
        _set(notify_emails='')
        from cis.services.hs_uploads import notify_hs_upload
        self.assertEqual(notify_hs_upload(self.upload(self.hs_a)), [])
        self.assertEqual(self._queued(), [])


class SettingInstallTests(TestCase):
    def test_install_keeps_customised_values(self):
        from django.http import HttpRequest
        _set(max_upload_mb=25)
        hs_uploads(HttpRequest()).install()
        value = Setting.objects.get(key=hs_uploads.key).value
        self.assertEqual(value['max_upload_mb'], 25)
        self.assertIn('allowed_extensions', value)


class TableModuleCheckTests(TestCase):
    def test_warns_when_module_missing(self):
        from cis.checks import hs_uploads_table_check
        self.assertEqual(hs_uploads_table_check(None), [])
        with mock.patch('cis.checks.importlib.util.find_spec', return_value=None):
            self.assertEqual([w.id for w in hs_uploads_table_check(None)], ['cis.W003'])


class MigrationTests(TestCase):
    def test_uploaded_on_is_set_once(self):
        field = HighSchoolTranscript._meta.get_field('uploaded_on')
        self.assertTrue(field.auto_now_add)
        self.assertFalse(field.auto_now)
