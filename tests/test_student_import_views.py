"""CE student import views against cis.tests.fake_tenant (package-cis#57)."""
import csv
import io

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.student import Student

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:
    _login_history_post_login = None

FAKE_TENANT = 'cis.tests.fake_tenant'

CSV = (
    'first_name,last_name,email,date_of_birth,fake_color,fake_meta_note,highschool_ceeb\n'
    'Ann,Lee,ann@example.com,05/14/2012,green,,480123\n'
)


@override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
class CEStudentImportViewTests(TestCase):
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
        Group.objects.get_or_create(name='student')
        ce = Group.objects.get_or_create(name='ce')[0]
        cls.hs = HighSchool.objects.create(name='Central HS', code='480123')
        cls.admin = CustomUser.objects.create(
            username='admin@x.com', email='admin@x.com', is_active=True)
        cls.admin.set_password('pw')
        cls.admin.save()
        cls.admin.groups.add(ce)

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.admin)

    def _upload(self):
        upload = SimpleUploadedFile('roster.csv', CSV.encode(), content_type='text/csv')
        return self.client.post(
            reverse('cis:student_import_upload'), {'file': upload}, follow=True)

    def test_template_download_has_the_tenant_columns(self):
        resp = self.client.get(reverse('cis:student_import_template'))
        self.assertEqual(resp.status_code, 200)
        headers = next(csv.reader(io.StringIO(resp.content.decode())))
        for name in ('highschool_ceeb', 'first_name', 'fake_color', 'fake_meta_note'):
            self.assertIn(name, headers)
        for name in ('fake_attestation', 'fake_hidden_code', 'password', 'highschool'):
            self.assertNotIn(name, headers)

    def test_upload_page_lists_tenant_field_definitions(self):
        resp = self.client.get(reverse('cis:student_import_upload'))
        self.assertEqual(resp.status_code, 200)
        names = {d['name'] for d in resp.context['field_definitions']}
        self.assertIn('fake_color', names)
        self.assertNotIn('fake_attestation', names)

    def test_upload_then_preview_then_confirm_creates_student(self):
        resp = self._upload()
        self.assertEqual(resp.status_code, 200)
        batch = resp.context['batch']
        row = batch.rows.get(row_number=1)
        self.assertEqual(row.status, 'valid', row.errors)

        confirm = self.client.post(
            reverse('cis:student_import_confirm', args=[batch.id]),
            {'selected_rows': [str(row.id)]})
        self.assertEqual(confirm.status_code, 200)
        student = Student.objects.get(user__email='ann@example.com')
        self.assertEqual(student.meta.get('fake_color'), 'green')

    def test_confirm_is_idempotent(self):
        resp = self._upload()
        batch = resp.context['batch']
        row = batch.rows.get(row_number=1)
        url = reverse('cis:student_import_confirm', args=[batch.id])
        self.client.post(url, {'selected_rows': [str(row.id)]})
        self.assertEqual(Student.objects.filter(user__email='ann@example.com').count(), 1)
        # second submit must not create another student
        resp2 = self.client.post(url, {'selected_rows': [str(row.id)]})
        self.assertEqual(resp2.context['summary']['created'], 0)
        self.assertEqual(Student.objects.filter(user__email='ann@example.com').count(), 1)

    def test_get_to_confirm_does_not_commit(self):
        from cis.models.student_import import StudentImportBatch
        batch = StudentImportBatch.objects.create(source_filename='x.csv', scope='ce')
        resp = self.client.get(
            reverse('cis:student_import_confirm', args=[batch.id]))
        self.assertIn(resp.status_code, (301, 302))
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'pending')
