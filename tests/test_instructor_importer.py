import datetime

from django.test import TestCase

from cis.services.importers.instructor_schema import InstructorRow


class InstructorRowSchemaTests(TestCase):
    BASE = {
        'teacherid': '01064335',
        'last_name': 'Abell',
        'first_name': 'Whitney',
        'middle_name': '',
        'highschool_ceeb': '480159',
        'teacher_id': 'wabell',
        'secondary_email': 'WABELL@ewu.edu',
        'primary_email': 'WABELL@cvsd.org',
        'home_email': '',
        'status': 'Active',
        'home_address': '623623 S Liberty Drive',
        'home_city': 'Liberty Lake',
        'home_state': 'WA',
        'home_zip': '99019',
        'cell_phone': '5095583868',
        'home_phone': '',
        'date_of_birth': '03/15/1988',
        'date_of_hire': '03/18/2025',
        'orientation_date': '08/11/2025',
        'course_1': 'PHED 150',
        'course_2': 'PHED 152',
    }

    def test_valid_row_parses_and_lowercases_emails(self):
        row = InstructorRow.model_validate(self.BASE)
        self.assertEqual(row.teacherid, '01064335')
        self.assertEqual(row.teacher_id, 'wabell')
        self.assertEqual(row.primary_email, 'wabell@cvsd.org')
        self.assertEqual(row.secondary_email, 'wabell@ewu.edu')

    def test_mdy_dates_are_parsed(self):
        row = InstructorRow.model_validate(self.BASE)
        self.assertEqual(row.date_of_birth, datetime.date(1988, 3, 15))
        self.assertEqual(row.date_of_hire, datetime.date(2025, 3, 18))
        self.assertEqual(row.orientation_date, datetime.date(2025, 8, 11))

    def test_blank_optionals_become_none(self):
        row = InstructorRow.model_validate(self.BASE)
        self.assertIsNone(row.middle_name)
        self.assertIsNone(row.home_email)
        self.assertIsNone(row.home_phone)

    def test_status_defaults_to_active_and_validates(self):
        data = dict(self.BASE, status='')
        self.assertEqual(InstructorRow.model_validate(data).status, 'Active')
        with self.assertRaises(Exception):
            InstructorRow.model_validate(dict(self.BASE, status='Bogus'))

    def test_course_columns_collected(self):
        row = InstructorRow.model_validate(self.BASE)
        self.assertEqual(row.course_1, 'PHED 150')
        self.assertEqual(row.course_2, 'PHED 152')
        self.assertIsNone(row.course_3)

    def test_required_fields_enforced(self):
        with self.assertRaises(Exception):
            InstructorRow.model_validate(dict(self.BASE, primary_email=''))

    def test_csv_headers_include_unique_course_columns(self):
        headers = InstructorRow.csv_headers()
        self.assertIn('teacherid', headers)
        self.assertIn('course_1', headers)
        self.assertIn('course_10', headers)
        # no duplicate "course_name" columns
        self.assertNotIn('course_name', headers)

    def test_iso_date_format_also_accepted(self):
        row = InstructorRow.model_validate(dict(self.BASE, date_of_birth='1988-03-15'))
        self.assertEqual(row.date_of_birth, datetime.date(1988, 3, 15))

    def test_lookup_and_db_field_mappings(self):
        self.assertIn('highschool_ceeb', InstructorRow.lookup_fields())
        self.assertNotIn('highschool_ceeb', InstructorRow.db_field_mapping())
        self.assertEqual(InstructorRow.db_field_mapping().get('teacherid'), 'psid')


from django.contrib.auth.models import Group

from cis.models.customuser import CustomUser
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate
from cis.models.highschool import HighSchool
from cis.models.course import Course, Cohort
from cis.services.importers.instructor_importer import InstructorImporter


def _make_course(name):
    cohort, _ = Cohort.objects.get_or_create(
        designator=name.split()[0], defaults={'name': name.split()[0]})
    return Course.objects.create(
        name=name, catalog_number=name.split()[-1], title=name, cohort=cohort)


class InstructorImporterTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='instructor')
        self.hs = HighSchool.objects.create(name='Liberty High', code='480159')
        _make_course('PHED 150')
        _make_course('PHED 152')

    def _row(self, **overrides):
        row = {
            'teacherid': '01064335', 'teacher_id': 'wabell',
            'last_name': 'Abell', 'first_name': 'Whitney', 'middle_name': '',
            'highschool_ceeb': '480159',
            'secondary_email': 'wabell@ewu.edu', 'primary_email': 'wabell@cvsd.org',
            'home_email': '', 'status': 'Active',
            'home_address': '1 Main', 'home_city': 'Liberty Lake',
            'home_state': 'WA', 'home_zip': '99019',
            'cell_phone': '5095583868', 'home_phone': '',
            'date_of_birth': '03/15/1988', 'date_of_hire': '03/18/2025',
            'orientation_date': '08/11/2025',
            'course_1': 'PHED 150', 'course_2': 'PHED 152',
        }
        row.update(overrides)
        return row

    def test_creates_teacher_user_highschool_and_certs(self):
        result = InstructorImporter().process_csv(iter([self._row()]))
        self.assertEqual(result['summary']['successful'], 1)

        teacher = Teacher.objects.get(user__psid='01064335')
        self.assertEqual(teacher.user.username, 'wabell')
        self.assertEqual(teacher.user.alt_username, 'wabell')
        self.assertEqual(teacher.user.email, 'wabell@cvsd.org')
        self.assertEqual(teacher.orientation_date, datetime.date(2025, 8, 11))
        self.assertTrue(teacher.user.groups.filter(name='instructor').exists())

        ths = TeacherHighSchool.objects.get(teacher=teacher, highschool=self.hs)
        self.assertEqual(ths.status, 'In the Program')

        certs = TeacherCourseCertificate.objects.filter(teacher_highschool=ths)
        self.assertEqual(certs.count(), 2)
        cert = certs.first()
        self.assertEqual(cert.status, 'Teaching')
        self.assertEqual(cert.since.date(), datetime.date(2025, 3, 18))

    def test_missing_course_is_skipped_row_still_succeeds(self):
        result = InstructorImporter().process_csv(
            iter([self._row(course_2='NOPE 999')]))
        self.assertEqual(result['summary']['successful'], 1)
        teacher = Teacher.objects.get(user__psid='01064335')
        ths = TeacherHighSchool.objects.get(teacher=teacher)
        self.assertEqual(
            TeacherCourseCertificate.objects.filter(teacher_highschool=ths).count(), 1)
        self.assertIn('NOPE 999', result['records'][0]['RESULT'])

    def test_unknown_ceeb_fails_row(self):
        result = InstructorImporter().process_csv(
            iter([self._row(highschool_ceeb='000000')]))
        self.assertEqual(result['summary']['failed'], 1)
        self.assertFalse(Teacher.objects.filter(user__psid='01064335').exists())

    def test_existing_teacher_reused_not_updated(self):
        user = CustomUser.objects.create(
            username='preexisting', email='pre@x.edu', psid='01064335',
            first_name='OLD', last_name='NAME')
        Teacher.objects.create(user=user, status='Inactive')

        result = InstructorImporter().process_csv(iter([self._row()]))
        self.assertEqual(result['summary']['successful'], 1)

        teacher = Teacher.objects.get(user__psid='01064335')
        self.assertEqual(teacher.user.first_name, 'OLD')
        self.assertEqual(teacher.user.username, 'preexisting')
        self.assertEqual(teacher.status, 'Inactive')
        self.assertTrue(
            TeacherHighSchool.objects.filter(teacher=teacher, highschool=self.hs).exists())
        self.assertEqual(
            TeacherCourseCertificate.objects.filter(
                teacher_highschool__teacher=teacher).count(), 2)

    def test_idempotent_rerun_no_duplicates(self):
        InstructorImporter().process_csv(iter([self._row()]))
        InstructorImporter().process_csv(iter([self._row()]))
        self.assertEqual(Teacher.objects.filter(user__psid='01064335').count(), 1)
        self.assertEqual(
            TeacherCourseCertificate.objects.filter(
                teacher_highschool__teacher__user__psid='01064335').count(), 2)


import csv
import io


class TeacherImportFromCsvTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='instructor')
        HighSchool.objects.create(name='Liberty High', code='480159')
        _make_course('PHED 150')

    def test_model_method_imports_from_dictreader(self):
        headers = InstructorRow.csv_headers()
        values = {h: '' for h in headers}
        values.update({
            'teacherid': '01064335', 'teacher_id': 'wabell',
            'last_name': 'Abell', 'first_name': 'Whitney',
            'highschool_ceeb': '480159', 'primary_email': 'wabell@cvsd.org',
            'status': 'Active', 'course_1': 'PHED 150',
        })
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=headers)
        writer.writeheader()
        writer.writerow(values)
        buf.seek(0)

        result = Teacher.import_from_csv(csv.DictReader(buf))
        self.assertEqual(result['summary']['successful'], 1)
        self.assertTrue(Teacher.objects.filter(user__psid='01064335').exists())


from django.test import Client
from django.urls import reverse
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:
    _login_history_post_login = None


class InstructorImportViewTests(TestCase):
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
        Group.objects.get_or_create(name='instructor')
        ce_group, _ = Group.objects.get_or_create(name='ce')
        HighSchool.objects.create(name='Liberty High', code='480159')
        _make_course('PHED 150')
        self.staff = CustomUser.objects.create(
            username='ce@x.edu', email='ce@x.edu', is_staff=True, is_superuser=True)
        self.staff.set_password('pw')
        self.staff.save()
        self.staff.groups.add(ce_group)
        self.client = Client()
        self.client.force_login(self.staff)

    def test_download_template_returns_csv_with_headers(self):
        resp = self.client.get(reverse('cis:instructor_download_template'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        body = resp.content.decode('utf-8')
        self.assertIn('teacherid', body)
        self.assertIn('course_10', body)

    def test_add_new_get_shows_import_card(self):
        resp = self.client.get(reverse('cis:instructor_add_new'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Import Instructors')

    def test_post_csv_imports_and_returns_results(self):
        headers = InstructorRow.csv_headers()
        values = {h: '' for h in headers}
        values.update({
            'teacherid': '01064335', 'teacher_id': 'wabell',
            'last_name': 'Abell', 'first_name': 'Whitney',
            'highschool_ceeb': '480159', 'primary_email': 'wabell@cvsd.org',
            'status': 'Active', 'course_1': 'PHED 150',
        })
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=headers)
        writer.writeheader()
        writer.writerow(values)
        upload = io.BytesIO(buf.getvalue().encode('utf-8'))
        upload.name = 'instructors.csv'

        resp = self.client.post(reverse('cis:instructor_add_new'), {
            'upload_file': 'Import Instructors',
            'file': upload,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        self.assertTrue(Teacher.objects.filter(user__psid='01064335').exists())
