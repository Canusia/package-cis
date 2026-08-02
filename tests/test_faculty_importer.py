import io
import csv
import tempfile
import os

from django.test import Client, TestCase
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

from cis.services.importers.faculty_schema import FacultyRow
from cis.models.faculty import FacultyCoordinator
from cis.models.course import Course, CourseAdministrator
from cis.services.importers.faculty_importer import FacultyImporter

User = get_user_model()


class FacultyRowSchemaTests(TestCase):
    def test_required_headers(self):
        req = FacultyRow.required_headers()
        self.assertEqual(set(req), {'email', 'first_name', 'last_name'})

    def test_email_lowercased_and_whitespace_stripped(self):
        r = FacultyRow.model_validate(
            {'email': '  Jane.Doe@Example.COM ', 'first_name': ' Jane ', 'last_name': 'Doe'})
        self.assertEqual(r.email, 'jane.doe@example.com')
        self.assertEqual(r.first_name, 'Jane')

    def test_role_normalized_to_canonical(self):
        r = FacultyRow.model_validate({
            'email': 'a@b.com', 'first_name': 'A', 'last_name': 'B',
            'course_1': 'ENGL 101', 'role_1': 'faculty',
            'course_2': 'MATH 200', 'role_2': 'VISITOR'})
        self.assertEqual(r.role_1, 'Faculty')
        self.assertEqual(r.role_2, 'Visitor')

    def test_role_passthrough_for_invalid(self):
        # Unknown role values are NOT rejected at the schema; the raw (trimmed)
        # value passes through so the importer can note it per-pair.
        r = FacultyRow.model_validate({
            'email': 'a@b.com', 'first_name': 'A', 'last_name': 'B',
            'course_1': 'ENGL 101', 'role_1': ' dean '})
        self.assertEqual(r.role_1, 'dean')

    def test_status_case_insensitive(self):
        r = FacultyRow.model_validate({
            'email': 'a@b.com', 'first_name': 'A', 'last_name': 'B',
            'status': 'active'})
        self.assertEqual(r.status, 'Active')
        r2 = FacultyRow.model_validate({
            'email': 'a@b.com', 'first_name': 'A', 'last_name': 'B',
            'status': 'INACTIVE'})
        self.assertEqual(r2.status, 'Inactive')

    def test_status_invalid_rejected(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            FacultyRow.model_validate({
                'email': 'a@b.com', 'first_name': 'A', 'last_name': 'B',
                'status': 'pending'})

    def test_course_role_pairs(self):
        pairs = FacultyRow.course_role_pairs()
        self.assertEqual(pairs[0], ('course_1', 'role_1'))
        self.assertEqual(len(pairs), 10)


def _make_course(name, status='Active'):
    """Create a minimal Active Course.

    Adjustments vs the brief's template:
    - Added ``stream=''`` — Course.stream is MultiSelectField(null=False, blank=True),
      so an empty string satisfies the DB constraint while keeping the helper minimal.
    """
    from cis.models.course import Cohort
    cohort, _ = Cohort.objects.get_or_create(
        designator='TST', defaults={'name': 'Test Cohort'})
    return Course.objects.create(
        name=name, catalog_number=name[-3:], title=name,
        cohort=cohort, status=status, stream='')


class FacultyImporterTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='faculty')
        self.engl = _make_course('ENGL 101')
        self.math = _make_course('MATH 200')

    def _run(self, rows):
        return FacultyImporter().process_csv(iter(rows))

    def test_creates_faculty_user_and_group(self):
        res = self._run([{'email': 'jane@example.com', 'first_name': 'Jane', 'last_name': 'Doe'}])
        self.assertEqual(res['summary']['successful'], 1)
        u = User.objects.get(email='jane@example.com')
        self.assertTrue(FacultyCoordinator.objects.filter(user=u).exists())
        self.assertTrue(u.groups.filter(name='faculty').exists())
        self.assertEqual(u.username, 'jane@example.com')  # username = email.lower()

    def test_assigns_courses_with_roles(self):
        self._run([{
            'email': 'jane@example.com', 'first_name': 'Jane', 'last_name': 'Doe',
            'course_1': 'ENGL 101', 'role_1': 'faculty',
            'course_2': 'MATH 200', 'role_2': 'visitor'}])
        u = User.objects.get(email='jane@example.com')
        self.assertTrue(CourseAdministrator.objects.filter(
            user=u, course=self.engl, role='Faculty').exists())
        self.assertTrue(CourseAdministrator.objects.filter(
            user=u, course=self.math, role='Visitor').exists())

    def test_existing_user_reused_not_duplicated(self):
        existing = User.objects.create(email='jane@example.com', username='jane@example.com',
                                       first_name='Jane', last_name='Doe')
        self._run([{'email': 'jane@example.com', 'first_name': 'Jane', 'last_name': 'Doe'}])
        self.assertEqual(User.objects.filter(email='jane@example.com').count(), 1)
        self.assertTrue(FacultyCoordinator.objects.filter(user=existing).exists())

    def test_unknown_course_fails_pair_not_row(self):
        res = self._run([{
            'email': 'jane@example.com', 'first_name': 'Jane', 'last_name': 'Doe',
            'course_1': 'NOPE 999', 'role_1': 'faculty'}])
        # row still succeeds (faculty created) but RESULT notes the bad course
        self.assertEqual(res['summary']['successful'], 1)
        self.assertIn('NOPE 999', res['records'][0]['RESULT'])

    def test_course_without_role_noted(self):
        res = self._run([{
            'email': 'jane@example.com', 'first_name': 'Jane', 'last_name': 'Doe',
            'course_1': 'ENGL 101', 'role_1': ''}])
        self.assertIn('role', res['records'][0]['RESULT'].lower())

    def test_invalid_email_row_fails(self):
        res = self._run([{'email': '', 'first_name': 'Jane', 'last_name': 'Doe'}])
        self.assertEqual(res['summary']['failed'], 1)

    def test_invalid_role_noted_per_pair_row_succeeds(self):
        # Invalid role on one pair is noted but does NOT fail the row; the
        # faculty account and any valid pairs are still created.
        res = self._run([{
            'email': 'jane@example.com', 'first_name': 'Jane', 'last_name': 'Doe',
            'course_1': 'ENGL 101', 'role_1': 'dean',
            'course_2': 'MATH 200', 'role_2': 'faculty'}])
        self.assertEqual(res['summary']['successful'], 1)
        result = res['records'][0]['RESULT']
        self.assertIn("invalid role 'dean'", result)
        u = User.objects.get(email='jane@example.com')
        self.assertTrue(FacultyCoordinator.objects.filter(user=u).exists())
        # the valid pair was still assigned
        self.assertTrue(CourseAdministrator.objects.filter(
            user=u, course=self.math, role='Faculty').exists())
        # the invalid pair was not
        self.assertFalse(CourseAdministrator.objects.filter(
            user=u, course=self.engl).exists())

    def test_role_with_blank_course_noted(self):
        res = self._run([{
            'email': 'jane@example.com', 'first_name': 'Jane', 'last_name': 'Doe',
            'course_1': '', 'role_1': 'faculty'}])
        self.assertEqual(res['summary']['successful'], 1)
        self.assertIn('course is blank', res['records'][0]['RESULT'])

    def test_duplicate_course_admin_does_not_fail_row(self):
        # Pre-existing duplicate (course, user, role) rows must not blow up the
        # import (no unique_together; get_or_add's .get() would raise).
        u = User.objects.create(email='jane@example.com', username='jane@example.com',
                                first_name='Jane', last_name='Doe')
        CourseAdministrator.objects.create(course=self.engl, user=u, role='Faculty')
        CourseAdministrator.objects.create(course=self.engl, user=u, role='Faculty')
        res = self._run([{
            'email': 'jane@example.com', 'first_name': 'Jane', 'last_name': 'Doe',
            'course_1': 'ENGL 101', 'role_1': 'faculty'}])
        self.assertEqual(res['summary']['successful'], 1)
        # no new row added (an existing match was found)
        self.assertEqual(CourseAdministrator.objects.filter(
            course=self.engl, user=u, role='Faculty').count(), 2)

    def test_existing_account_promoted_noted(self):
        # An existing non-faculty user gets the faculty role + a RESULT note.
        existing = User.objects.create(email='jane@example.com', username='jane@example.com',
                                       first_name='Jane', last_name='Doe')
        res = self._run([{
            'email': 'jane@example.com', 'first_name': 'Jane', 'last_name': 'Doe'}])
        self.assertEqual(res['summary']['successful'], 1)
        result = res['records'][0]['RESULT']
        self.assertIn('added faculty role to existing account', result)
        self.assertIn('jane@example.com', result)
        self.assertTrue(FacultyCoordinator.objects.filter(user=existing).exists())


class FacultyModelEntryTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='faculty')

    def test_import_from_csv_staticmethod(self):
        res = FacultyCoordinator.import_from_csv(
            iter([{'email': 'x@y.com', 'first_name': 'X', 'last_name': 'Y'}]))
        self.assertEqual(res['summary']['successful'], 1)
        self.assertTrue(User.objects.filter(email='x@y.com').exists())


class FacultyImportViewTests(TestCase):
    def _login(self, user):
        """force_login via Django test Client, neutralising the login-history signal."""
        from django.contrib.auth.signals import user_logged_in
        from django_login_history.models import post_login
        user_logged_in.disconnect(post_login)
        try:
            c = Client()
            c.force_login(user)
        finally:
            user_logged_in.connect(post_login)
        return c

    def setUp(self):
        Group.objects.get_or_create(name='faculty')
        self.ce = User.objects.create(email='ce@example.com', username='ce@example.com')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.c = self._login(self.ce)

    def test_download_template_has_headers(self):
        resp = self.c.get(reverse('cis:faculty_coordinator_download_template'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('email', resp.content.decode())
        self.assertIn('course_1', resp.content.decode())

    def test_upload_creates_faculty_and_returns_results_csv(self):
        _make_course('ENGL 101')
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['email', 'first_name', 'last_name', 'course_1', 'role_1'])
        w.writerow(['jane@example.com', 'Jane', 'Doe', 'ENGL 101', 'faculty'])
        upload = io.BytesIO(buf.getvalue().encode('utf-8'))
        upload.name = 'faculty.csv'
        resp = self.c.post(reverse('cis:faculty_coordinator_add_new'),
                           {'upload_file': 'Import Faculty', 'file': upload})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('RESULT', resp.content.decode())
        self.assertTrue(User.objects.filter(email='jane@example.com').exists())


class FacultyImportCommandTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='faculty')

    def test_command_imports_from_path(self):
        fd, path = tempfile.mkstemp(suffix='.csv')
        with os.fdopen(fd, 'w') as fh:
            fh.write('email,first_name,last_name\n')
            fh.write('cmd@example.com,Cmd,User\n')
        results_path = path + '.results.csv'
        try:
            call_command('import_faculty', '-p', path)
            self.assertTrue(os.path.exists(results_path), "results CSV should be written")
            with open(results_path) as rf:
                self.assertIn('RESULT', rf.read())
            self.assertTrue(User.objects.filter(email='cmd@example.com').exists())
        finally:
            os.remove(path)
            if os.path.exists(results_path):
                os.remove(results_path)
