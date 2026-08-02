"""PT-34: /ce/section/import_from_s3 must be CIS-only.

Pentest finding PT-34 (Medium): the section-import endpoint was exposed
without authentication, executing backend import logic for anonymous
callers. The fix requires authentication AND the 'ce' (CIS) role:

  * anonymous           -> 302 redirect to '/' (login), handler NOT run
  * authenticated, non-CE -> 302 redirect to '/' (user_passes_test), handler NOT run
  * authenticated CE      -> handler runs (NOT redirected to '/')

The route is guarded by user_passes_test(user_has_cis_role, login_url='/'),
so denial is a 302 redirect (not a 403). See the plan for the
redirect-vs-403 rationale.
"""
from unittest.mock import patch
from urllib.parse import urlparse

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

IMPORT_URL = '/ce/section/import_from_s3'


class ImportFromS3AuthTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler blows up in tests
        # because the request has no usable IP. Disconnect for the duration
        # of this test case (mirrors test_teacher_course_viewset_filters.py).
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
        Group.objects.get_or_create(name='highschool_admin')

        cls.ce_user = User.objects.create_user(
            username='ce_pt34', email='ce_pt34@example.com',
            password='x', first_name='C', last_name='E', is_staff=True,
        )
        cls.ce_user.groups.add(Group.objects.get(name='ce'))

        cls.hs_admin = User.objects.create_user(
            username='hsa_pt34', email='hsa_pt34@example.com',
            password='x', first_name='H', last_name='A',
        )
        cls.hs_admin.groups.add(Group.objects.get(name='highschool_admin'))

    def setUp(self):
        # cis LoginRequiredMiddleware checks request.user.is_authenticated,
        # which is set by Session/Authentication middleware, so a real session
        # login is required (force_authenticate alone is not enough).
        # raise_request_exception=False lets the CE-path test observe the
        # handler's response (the no-file branch returns None -> Django 500)
        # instead of re-raising it as a test error; the denial tests never
        # reach the handler so this does not affect them.
        self.client = self.client_class(
            REMOTE_ADDR='127.0.0.1', raise_request_exception=False
        )

    def test_url_name_resolves_to_endpoint(self):
        # Guards against the route being renamed out from under these tests.
        self.assertEqual(reverse('cis:import_sections_from_s3'), IMPORT_URL)

    def test_anonymous_is_redirected_and_handler_not_run(self):
        with patch('cis.views.section.get_uploaded_file') as mocked:
            resp = self.client.get(IMPORT_URL)
        self.assertEqual(resp.status_code, 302)
        # Redirected to the login landing page ('/'); Django's auth wrappers
        # append a ?next= query, so compare the path only.
        self.assertEqual(urlparse(resp.url).path, '/')
        mocked.assert_not_called()

    def test_non_ce_user_is_redirected_and_handler_not_run(self):
        self.client.force_login(self.hs_admin)
        with patch('cis.views.section.get_uploaded_file') as mocked:
            resp = self.client.get(IMPORT_URL)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(urlparse(resp.url).path, '/')
        mocked.assert_not_called()

    def test_ce_user_reaches_handler(self):
        self.client.force_login(self.ce_user)
        # Mock the S3 read so the handler does not hit external storage.
        # Returning None makes the view take the no-file branch, which now
        # flashes a message and redirects to cis:section_add_new (no longer a
        # None -> 500). That the handler ran at all (mock called) and was NOT
        # redirected to the login landing page '/' proves the CE user passed
        # both the auth and the user_has_cis_role gates.
        with patch('cis.views.section.get_uploaded_file', return_value=None) as mocked:
            resp = self.client.get(IMPORT_URL)
        # The handler ran (it reached get_uploaded_file). It is NOT redirected
        # to login ('/'), which is what distinguishes an authorized CE user
        # from the denied anonymous / non-CE cases above. The handler's own
        # no-file redirect (to section_add_new) is a different target.
        mocked.assert_called()
        self.assertNotEqual(urlparse(resp.url).path, '/')
