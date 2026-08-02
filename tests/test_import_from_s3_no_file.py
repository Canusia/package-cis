"""import_from_s3 must always return an HttpResponse (never None -> 500).

The view reads a class-export CSV from S3. When the file is missing, the
import errors, or the import succeeds with zero rows, the view must flash a
message and redirect back to the section add-new page instead of falling
through to a 500. The endpoint is CIS-only (PT-34), so tests log in as CE.
"""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()


class ImportFromS3NoFileTests(TestCase):
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
        ce = User.objects.create_user(
            username='ce_s3', email='ce_s3@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce
        cls.url = reverse('cis:import_sections_from_s3')
        cls.redirect_url = reverse('cis:section_add_new')

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.ce_user)

    @patch('cis.views.section.get_uploaded_file', return_value=None)
    def test_no_file_redirects_not_500(self, _mock):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, self.redirect_url)

    @patch('cis.views.section.get_uploaded_file', return_value='')
    def test_empty_file_redirects_not_500(self, _mock):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, self.redirect_url)

    @patch('cis.views.section.ClassSection.import_from_csv',
           return_value={'status': 'error', 'message': 'bad data'})
    @patch('cis.views.section.get_uploaded_file', return_value='header\nrow')
    def test_error_result_redirects_not_500(self, _mock_file, _mock_import):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, self.redirect_url)

    @patch('cis.views.section.ClassSection.import_from_csv',
           return_value={'status': 'success', 'records': []})
    @patch('cis.views.section.get_uploaded_file', return_value='header\nrow')
    def test_success_with_no_rows_redirects_not_500(self, _mock_file, _mock_import):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, self.redirect_url)

    @patch('cis.views.section.ClassSection.import_from_csv',
           return_value={'status': 'success', 'records': [{'a': 1, 'b': 2}]})
    @patch('cis.views.section.get_uploaded_file', return_value='header\nrow')
    def test_success_streams_csv(self, _mock_file, _mock_import):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        self.assertIn('attachment', resp['Content-Disposition'])
