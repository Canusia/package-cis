import io
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from cis.models.highschool import HighSchool
from cis.models.customuser import CustomUser
from cis.models.student import Student

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:
    _login_history_post_login = None

CSV = (
    'first_name,last_name,email,permanent_address_country,permanent_address,'
    'city,state,zip_code,preferred_phone,home_phone,cell_phone,legal_sex,'
    'date_of_birth,start_date,graduation_date,highschool_ceeb,same_as_permanent,mailing_address\n'
    'Ann,Lee,ann@example.com,US,1 Main St,Spokane,WA,99201,Mobile,'
    '5095551234,5095559999,f,05/14/2012,09/01/2026,06/01/2028,480123,true,\n'
)


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
        cls.admin.set_password('pw'); cls.admin.save()
        cls.admin.groups.add(ce)

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.admin)

    def test_template_download_has_headers(self):
        resp = self.client.get(reverse('cis:student_import_template'))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('highschool_ceeb', body)
        self.assertIn('first_name', body)

    def test_upload_then_preview_then_confirm_creates_student(self):
        upload = SimpleUploadedFile('roster.csv', CSV.encode(), content_type='text/csv')
        resp = self.client.post(
            reverse('cis:student_import_upload'), {'file': upload}, follow=True)
        self.assertEqual(resp.status_code, 200)
        batch = resp.context['batch']
        row = batch.rows.get(row_number=1)
        self.assertEqual(row.status, 'valid')

        confirm = self.client.post(
            reverse('cis:student_import_confirm', args=[batch.id]),
            {'selected_rows': [str(row.id)]})
        self.assertEqual(confirm.status_code, 200)
        self.assertTrue(Student.objects.filter(user__email='ann@example.com').exists())

    def test_confirm_is_idempotent(self):
        upload = SimpleUploadedFile('roster.csv', CSV.encode(), content_type='text/csv')
        resp = self.client.post(
            reverse('cis:student_import_upload'), {'file': upload}, follow=True)
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
