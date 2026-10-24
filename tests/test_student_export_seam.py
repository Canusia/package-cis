"""Student data export (#114 item 5): the format is tenant-overridable
(services/student_export.py HEADERS / build_row / CSV_OPTIONS) and the
student_exporter setting can send the file to the site's S3 bucket instead
of SFTP, with the SFTP fields required only for SFTP."""
import csv
import io
import uuid
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from cis.models.student import Student
from cis.reports.undup_students import undup_students
from cis.services import student_export

User = get_user_model()


def _tenant(headers=None, build_row=None, options=None):
    values = {'HEADERS': headers, 'build_row': build_row, 'CSV_OPTIONS': options}
    return mock.patch.object(
        student_export, 'get_tenant_override',
        lambda m, a: values.get(a) if m == 'student_export' else None)


class StudentExportFormatTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        sfx = uuid.uuid4().hex[:6]
        user = User.objects.create_user(
            username=f'exp_{sfx}', email=f'exp_{sfx}@x.com', password='x',
            first_name='Ann', last_name='Lee')
        self.student = Student.objects.create(
            user=user, account_verified=True, application_status='pending')
        self.saved = {}

    def _run(self, data):
        def save(storage, path, content):
            self.saved['path'] = path
            self.saved['text'] = content.read().decode('utf-8')
            return path
        with mock.patch('cis.reports.undup_students.PrivateMediaStorage.save', save), \
                mock.patch('cis.reports.undup_students.PrivateMediaStorage.url',
                           lambda storage, path: path):
            return undup_students().run(SimpleNamespace(id='t1'), data)

    def _rows(self, delimiter=','):
        return list(csv.reader(io.StringIO(self.saved['text']), delimiter=delimiter))

    def test_default_format_is_unchanged(self):
        with _tenant():
            self._run({'mark_as_sent': ['0'], 'send_to_slate': ['0']})
        rows = self._rows()
        self.assertEqual(rows[0][:2], ['Created', 'Canusia App ID'])
        self.assertIn('Ann', rows[1])

    def test_tenant_format(self):
        def build_row(record, imported_at):
            return [record.user.first_name, record.user.last_name]
        with _tenant(['FIRST', 'LAST'], build_row, {'delimiter': '|'}):
            self._run({'mark_as_sent': ['0'], 'send_to_slate': ['0']})
        self.assertEqual(self._rows('|'), [['FIRST', 'LAST'], ['Ann', 'Lee']])

    def test_headers_without_build_row_is_an_error(self):
        with _tenant(['FIRST']), self.assertRaises(ValueError):
            self._run({'mark_as_sent': ['0'], 'send_to_slate': ['0']})

    def test_s3_destination_writes_to_the_export_storage(self):
        from cis.settings.student_exporter import student_exporter
        written = {}

        def save(storage, path, content):
            written[path] = content.read().decode('utf-8')
            return path

        with _tenant(), \
                mock.patch.object(student_exporter, 'from_db', return_value={
                    'destination': 's3', 'path_to_file': 'exports/{{yyyy}}.csv'}), \
                mock.patch('cis.backends.storage_backend.StudentExportStorage.save', save), \
                mock.patch('cis.utils.sftp_connect') as sftp:
            count, path = undup_students().run(
                None, {'mark_as_sent': ['1'], 'send_to_slate': ['1']})
        sftp.assert_not_called()
        self.assertEqual(count, 1)
        self.assertRegex(path, r'^exports/\d{4}\.csv$')
        self.assertIn('Ann', written[path])
        self.student.refresh_from_db()
        self.assertEqual(self.student.application_status, 'in_review')


class StudentExporterSettingTests(TestCase):
    def _form(self, **data):
        from cis.settings.student_exporter import student_exporter
        request = RequestFactory().get('/', {'report_id': '1'})
        base = {'is_active': 'No', 'cron': '0 1 * * *', 'path_to_file': 'out.csv'}
        return student_exporter(request, data={**base, **data})

    def test_s3_needs_no_sftp_fields(self):
        form = self._form(destination='s3')
        self.assertTrue(form.is_valid(), form.errors)

    def test_sftp_requires_the_connection_fields(self):
        form = self._form(destination='sftp')
        self.assertFalse(form.is_valid())
        self.assertIn('host_name', form.errors)
        self.assertIn('username', form.errors)
