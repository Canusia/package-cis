"""Download filenames go through django.utils.http.content_disposition_header (#15).

A hand-built `attachment; filename="{name}"` breaks when the name holds a double
quote (unescaped) or any non-Latin-1 character such as the curly apostrophe
phones and Word insert (Django then MIME-encodes the whole header). The helper
escapes quotes and emits an RFC 5987 `filename*` instead.

The student PDF is the reported case, since its filename is built from the
student's name. The source scan below keeps the hand-built pattern from coming
back anywhere in the package.
"""
import pathlib
import re
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils.http import content_disposition_header

from cis.models.student import Student

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

CIS_ROOT = pathlib.Path(__file__).resolve().parent.parent


class StudentPdfFilenameTests(TestCase):
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
        ce, _ = Group.objects.get_or_create(name='ce')
        cls.admin = User.objects.create_superuser(
            username='cd_admin', email='cd_admin@example.com', password='x')
        cls.admin.groups.add(ce)

    def _download(self, last_name, first_name='Ann'):
        user = User.objects.create_user(
            username=f'cd-{uuid.uuid4().hex[:8]}',
            email=f'{uuid.uuid4().hex[:8]}@example.com', password='x',
            first_name=first_name, last_name=last_name)
        student = Student.objects.create(user=user)
        self.client.force_login(self.admin)
        with mock.patch.object(Student, 'as_pdf', return_value=b'%PDF-1.4'):
            return self.client.get(reverse('cis:student_pdf', args=[student.id]))

    def test_curly_apostrophe_uses_rfc5987_filename(self):
        resp = self._download('O’Brien')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp['Content-Disposition'],
            content_disposition_header(True, 'student-O’Brien-Ann.pdf'))
        self.assertIn("filename*=utf-8''", resp['Content-Disposition'])

    def test_double_quote_is_escaped(self):
        resp = self._download('Jo"hn')
        self.assertEqual(resp['Content-Disposition'],
                         'attachment; filename="student-Jo\\"hn-Ann.pdf"')

    def test_plain_ascii_name_unchanged(self):
        resp = self._download("O'Brien")
        self.assertEqual(resp['Content-Disposition'],
                         'attachment; filename="student-O\'Brien-Ann.pdf"')


class NoHandBuiltDynamicFilenameTests(SimpleTestCase):
    """Any Content-Disposition whose filename is computed must use the helper.

    Fixed string literals (e.g. "course_import_template.csv") are left alone:
    they cannot contain the characters that break the header.
    """
    HAND_BUILT = re.compile(
        r"""\[['"]Content-Disposition['"]\]\s*=\s*\\?\s*"""
        r"""(f['"].*filename=.*\{|['"].*filename=['"]\s*\+)""")

    def test_no_dynamic_hand_built_headers(self):
        offenders = []
        for path in CIS_ROOT.rglob('*.py'):
            if 'tests' in path.relative_to(CIS_ROOT).parts:
                continue
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                if self.HAND_BUILT.search(line):
                    offenders.append(f'{path.relative_to(CIS_ROOT)}:{lineno}')
        self.assertEqual(offenders, [])
