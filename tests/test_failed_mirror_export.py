"""CSV export on /ce/registrations/failed-mirror/.

The page's table is serverSide, so DataTables' own CSV button only ever sees
one page of rows. These cover the export-all endpoint, whose whole reason to
exist is that it ignores paging.
"""
import csv
import io

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models.course import Campus, Cohort, Course
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.term import AcademicYear, Term
from cis.views.registration_failed_mirror import EXPORT_COLUMNS


def _disconnect_login_signal():
    """django_login_history's post_login receiver crashes on the test client's
    missing REMOTE_ADDR."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


class FailedMirrorExportTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        # Student.save() assigns this group and blows up if it is absent.
        Group.objects.get_or_create(name='student')
        # The post_save signal on StudentRegistration adds a student note, and
        # with no request in scope it attributes it to the 'cron' user.
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})
        self.user = CustomUser.objects.create_superuser(
            email='ce-fm@example.com', username='ce-fm@example.com', password='pw')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)
        self.url = reverse('cis:registrations_failed_mirror_export')

        campus = Campus.objects.create(name='FM Campus', code='FMC')
        year = AcademicYear.objects.create(name='2028-2029', campus=campus)
        self.term = Term.objects.create(academic_year=year, code='FM1',
                                        label='FM Term')
        cohort = Cohort.objects.create(designator='FM', name='FM Cohort')
        course = Course.objects.create(cohort=cohort, catalog_number='200',
                                       name='FM 200', title='Mirror 200',
                                       campus=campus)
        hs = HighSchool.objects.create(name='FM HS', code='FMHS1')
        self.section = ClassSection.objects.create(
            course=course, term=self.term, highschool=hs)

        # 30 failed + 1 succeeded: more than one page, and one row that must
        # never appear in the export.
        self.failed = [self._registration(i, 'failed') for i in range(30)]
        self.ok = self._registration(99, 'success')

    def tearDown(self):
        user_logged_in.receivers = self._saved

    def _registration(self, index, mirror_status):
        user = CustomUser.objects.create_user(
            email=f'fm{index}@example.com', username=f'fm{index}@example.com',
            password='pw', first_name='First', last_name=f'Last{index:02d}',
            psid=f'PS{index:04d}')
        student = Student.objects.create(user=user)
        return StudentRegistration.objects.create(
            student=student, class_section=self.section,
            # status_changed_on is NOT NULL with no default.
            status_changed_on={'applied_on': '01/01/2028'},
            last_mirror_status=mirror_status)

    def _rows(self, response):
        content = response.content.decode('utf-8')
        return list(csv.reader(io.StringIO(content)))

    def test_exports_every_failed_row_not_just_a_page(self):
        rows = self._rows(self.client.get(self.url))

        self.assertEqual(len(rows) - 1, 30)   # minus the header

    def test_excludes_registrations_that_did_not_fail(self):
        body = self.client.get(self.url).content.decode('utf-8')

        self.assertNotIn('PS0099', body)

    def test_header_matches_the_declared_columns(self):
        rows = self._rows(self.client.get(self.url))

        self.assertEqual(rows[0], [header for _, header in EXPORT_COLUMNS])

    def test_needs_mirroring_renders_as_yes_no(self):
        target = self.failed[0]
        target.needs_mirroring = True
        target.save()

        rows = self._rows(self.client.get(self.url))
        column = EXPORT_COLUMNS.index(('needs_mirroring', 'Needs Mirroring'))
        values = {row[column] for row in rows[1:]}

        self.assertTrue(values.issubset({'Yes', 'No'}))
        self.assertIn('Yes', values)

    def test_is_a_csv_attachment(self):
        response = self.client.get(self.url)

        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('attachment; filename=', response['Content-Disposition'])
        self.assertIn('failed_mirror_registrations_', response['Content-Disposition'])

    def test_requires_a_cis_role(self):
        self.client.logout()
        outsider = CustomUser.objects.create_user(
            email='nobody@example.com', username='nobody@example.com',
            password='pw')
        self.client.force_login(outsider)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
