"""Class-section importer tenant knobs (package-cis#114 item 10).

Every knob is read from the tenant's `class_section_import` service module and
defaults to the package behaviour; each test below covers the default and the
knob switched on.
"""
import datetime
import uuid
from typing import Optional
from unittest import mock

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from pydantic import Field

from cis.models import ClassSection
from cis.models.course import Cohort, Course
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher, TeacherCourseCertificate, TeacherHighSchool
from cis.models.term import AcademicYear, Term
from cis.services.importers.class_section_importer import ClassSectionImporter
from cis.services.importers.class_section_schema import (
    ClassSectionRow, class_section_row_schema)
from cis.tests.fake_tenant.services import class_section_import as knobs

FAKE_TENANT = 'cis.tests.fake_tenant'


def knob(name, value):
    return mock.patch.object(knobs, name, value, create=True)


class DueDatesRow(ClassSectionRow):
    """A tenant ROW_SCHEMA adding the four section due dates."""
    registration_start_date: Optional[datetime.date] = Field(
        default=None, description="Registration window start",
        json_schema_extra={"db_field": "registration_start_date"})
    registration_end_date: Optional[datetime.date] = Field(
        default=None, description="Registration window end",
        json_schema_extra={"db_field": "registration_end_date"})
    payment_due_date: Optional[datetime.date] = Field(
        default=None, description="Payment due date",
        json_schema_extra={"db_field": "payment_due_date"})
    grade_due_date: Optional[datetime.date] = Field(
        default=None, description="Grade due date",
        json_schema_extra={"db_field": "grade_due_date"})


def _sfx():
    return uuid.uuid4().hex[:6]


@override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
class ClassSectionKnobTestBase(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='instructor')
        self.code = _sfx()
        self.term = Term.objects.create(
            academic_year=AcademicYear.objects.create(name=f'AY{_sfx()}'),
            code=self.code, label='Fall')
        self.hs = HighSchool.objects.create(name='Liberty High', code=_sfx())

    def row(self, **overrides):
        row = {
            'name': 'Fall', 'term_code': self.code,
            'reference_number': overrides.pop('reference_number', _sfx()),
            'section_number': '01', 'course_name': 'BIO 101',
            'course_title': 'Biology', 'registration_term_code': self.code,
            'highschool_ceeb': self.hs.code,
        }
        row.update(overrides)
        return row

    def run_import(self, *rows, bulk=True):
        return ClassSectionImporter(use_bulk_operations=bulk).process_csv(iter(rows))

    def section(self, row):
        return ClassSection.objects.get(term=self.term, class_number=row['reference_number'])

    def teacher(self, email, psid=None, first='Pat', last='Lee'):
        user = CustomUser.objects.create(
            username=f'u{_sfx()}', email=f'{_sfx()}@login.test',
            secondary_email=email, psid=psid, first_name=first, last_name=last)
        return Teacher.objects.create(user=user)


class PlainFixImportTests(ClassSectionKnobTestBase):
    def test_leading_zero_crn_kept_and_reimport_updates(self):
        row = self.row(reference_number='01234', tuition='$1,200')
        self.assertEqual(self.run_import(dict(row))['summary']['successful'], 1)
        section = self.section(row)
        self.assertEqual(section.class_number, '01234')
        self.assertEqual(float(section.tuition), 1200.0)

        # Bulk re-import finds the existing section by its text CRN.
        self.run_import(dict(row, tuition='99'))
        self.assertEqual(ClassSection.objects.filter(class_number='01234').count(), 1)
        self.assertEqual(float(self.section(row).tuition), 99.0)


class TeacherMatchTests(ClassSectionKnobTestBase):
    def test_default_exact_email_only(self):
        t = self.teacher('pat@hs.test')
        row = self.row(teacher_hs_email='pat@hs.test')
        self.run_import(row)
        self.assertEqual(self.section(row).teacher, t)

        row2 = self.row(teacher_hs_email='PAT@hs.test')
        self.run_import(row2)
        self.assertIsNone(self.section(row2).teacher)

    def test_default_offers_no_instructor_columns(self):
        headers = class_section_row_schema().csv_headers()
        self.assertNotIn('instructor_id', headers)
        self.assertNotIn('instructor_firstname', headers)

    def test_iexact_email(self):
        t = self.teacher('pat@hs.test')
        row = self.row(teacher_hs_email=' PAT@HS.test ')
        with knob('TEACHER_EMAIL_IEXACT', True):
            self.run_import(row)
        self.assertEqual(self.section(row).teacher, t)

    def test_psid_first(self):
        by_email = self.teacher('pat@hs.test')
        by_psid = self.teacher('other@hs.test', psid='P123')
        row = self.row(teacher_hs_email='pat@hs.test', instructor_id='P123')
        with knob('TEACHER_MATCH_ORDER', ('psid', 'email')):
            self.assertIn('instructor_id', class_section_row_schema().csv_headers())
            self.run_import(row)
        self.assertEqual(self.section(row).teacher, by_psid)
        self.assertNotEqual(by_psid, by_email)

    def test_psid_falls_back_to_email(self):
        t = self.teacher('pat@hs.test')
        row = self.row(teacher_hs_email='pat@hs.test', instructor_id='NOPE')
        with knob('TEACHER_MATCH_ORDER', ('psid', 'email')):
            self.run_import(row)
        self.assertEqual(self.section(row).teacher, t)
        t.user.refresh_from_db()
        self.assertIsNone(t.user.psid)  # no backfill by default

    def test_backfill_psid(self):
        t = self.teacher('pat@hs.test')
        row = self.row(teacher_hs_email='pat@hs.test', instructor_id='P777')
        with knob('BACKFILL_TEACHER_PSID', True):
            self.run_import(row)
        t.user.refresh_from_db()
        self.assertEqual(t.user.psid, 'P777')

    def test_backfill_never_overwrites_or_steals(self):
        t = self.teacher('pat@hs.test', psid='OLD')
        other = self.teacher('x@hs.test')
        CustomUser.objects.filter(pk=other.user.pk).update(psid='TAKEN')
        t2 = self.teacher('sam@hs.test')
        with knob('BACKFILL_TEACHER_PSID', True):
            self.run_import(self.row(teacher_hs_email='pat@hs.test', instructor_id='NEW'),
                            self.row(teacher_hs_email='sam@hs.test', instructor_id='TAKEN'))
        t.user.refresh_from_db()
        t2.user.refresh_from_db()
        self.assertEqual(t.user.psid, 'OLD')
        self.assertIsNone(t2.user.psid)


class AutoCreateTeacherTests(ClassSectionKnobTestBase):
    def named_row(self, **overrides):
        return self.row(teacher_hs_email='New.Teacher@HS.test',
                        instructor_firstname='New', instructor_lastname='Teacher',
                        instructor_id='P900', **overrides)

    def test_default_leaves_section_without_teacher(self):
        row = self.row(teacher_hs_email='new@hs.test')
        self.assertEqual(self.run_import(row)['summary']['successful'], 1)
        self.assertIsNone(self.section(row).teacher)
        self.assertFalse(CustomUser.objects.filter(email='new@hs.test').exists())

    def test_creates_teacher_link_and_certificate(self):
        row = self.named_row()
        with knob('AUTO_CREATE_TEACHER', True):
            self.assertIn('instructor_firstname', class_section_row_schema().csv_headers())
            self.run_import(row)
        teacher = self.section(row).teacher
        self.assertIsNotNone(teacher)
        user = teacher.user
        self.assertEqual(user.email, 'new.teacher@hs.test')
        self.assertEqual(user.secondary_email, 'new.teacher@hs.test')
        self.assertEqual((user.first_name, user.last_name, user.psid), ('New', 'Teacher', 'P900'))
        self.assertTrue(user.groups.filter(name='instructor').exists())
        ths = TeacherHighSchool.objects.get(teacher=teacher, highschool=self.hs)
        cert = TeacherCourseCertificate.objects.get(teacher_highschool=ths)
        self.assertEqual(cert.status, 'Teaching')
        self.assertEqual(cert.course.name, 'BIO 101')

    def test_individual_mode_too(self):
        row = self.named_row()
        with knob('AUTO_CREATE_TEACHER', True):
            self.run_import(row, bulk=False)
        self.assertIsNotNone(self.section(row).teacher)

    def test_requires_names_by_default(self):
        row = self.row(teacher_hs_email='new@hs.test')
        with knob('AUTO_CREATE_TEACHER', True):
            self.run_import(row)
        self.assertIsNone(self.section(row).teacher)
        self.assertFalse(CustomUser.objects.filter(email='new@hs.test').exists())

    def test_names_optional_creates_without_certificate(self):
        row = self.row(teacher_hs_email='new@hs.test')
        with knob('AUTO_CREATE_TEACHER', True), knob('AUTO_CREATE_REQUIRES_NAMES', False):
            self.run_import(row)
        teacher = self.section(row).teacher
        self.assertIsNotNone(teacher)
        self.assertFalse(TeacherCourseCertificate.objects.filter(
            teacher_highschool__teacher=teacher).exists())

    def test_cert_status_knob(self):
        row = self.named_row()
        with knob('AUTO_CREATE_TEACHER', True), knob('AUTO_CREATE_CERT_STATUS', 'Applicant'):
            self.run_import(row)
        self.assertEqual(TeacherCourseCertificate.objects.get(
            teacher_highschool__teacher=self.section(row).teacher).status, 'Applicant')

    def test_cert_status_none_means_no_certificate(self):
        row = self.named_row()
        with knob('AUTO_CREATE_TEACHER', True), knob('AUTO_CREATE_CERT_STATUS', None):
            self.run_import(row)
        teacher = self.section(row).teacher
        self.assertIsNotNone(teacher)
        self.assertFalse(TeacherCourseCertificate.objects.filter(
            teacher_highschool__teacher=teacher).exists())

    def test_no_high_school_no_create(self):
        row = self.named_row(highschool_ceeb='')
        with knob('AUTO_CREATE_TEACHER', True):
            self.run_import(row)
        self.assertIsNone(self.section(row).teacher)

    def test_reuses_existing_login_user(self):
        user = CustomUser.objects.create(
            username='new.teacher@hs.test', email='new.teacher@hs.test')
        row = self.named_row()
        with knob('AUTO_CREATE_TEACHER', True):
            self.run_import(row)
        self.assertEqual(self.section(row).teacher.user, user)
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.psid), ('New', 'P900'))

    def test_two_rows_one_new_teacher(self):
        a, b = self.named_row(), self.named_row()
        with knob('AUTO_CREATE_TEACHER', True):
            self.run_import(a, b)
        self.assertEqual(self.section(a).teacher, self.section(b).teacher)
        self.assertEqual(Teacher.objects.filter(user__email='new.teacher@hs.test').count(), 1)


class SectionDateTests(ClassSectionKnobTestBase):
    def test_us_style_four_digit_dates(self):
        row = self.row(start_date='8/25/2026', end_date='12-11-2026')
        self.run_import(row)
        section = self.section(row)
        self.assertEqual(section.start_date, datetime.date(2026, 8, 25))
        self.assertEqual(section.end_date, datetime.date(2026, 12, 11))

    def test_iso_still_accepted(self):
        row = self.row(start_date='2026-08-25')
        self.run_import(row)
        self.assertEqual(self.section(row).start_date, datetime.date(2026, 8, 25))

    def test_two_digit_year_rejected_by_default(self):
        result = self.run_import(self.row(start_date='8/25/26'))
        self.assertEqual(result['summary']['failed'], 1)
        self.assertIn('four-digit year', result['records'][0]['RESULT'])

    def test_two_digit_year_knob(self):
        row = self.row(start_date='8/25/26')
        with knob('CLASS_SECTION_IMPORT_ALLOW_2DIGIT_YEAR', True):
            self.run_import(row)
        self.assertEqual(self.section(row).start_date, datetime.date(2026, 8, 25))


class CourseNamePatternTests(ClassSectionKnobTestBase):
    PATTERN = r'^\s*([A-Za-z]+)\s*(\d.*)$'

    def test_default_requires_a_space(self):
        result = self.run_import(self.row(course_name='BIO101'))
        self.assertEqual(result['summary']['failed'], 1)

    def test_default_cohort_is_the_first_word(self):
        row = self.row(course_name='bio 202')
        self.run_import(row)
        self.assertEqual(self.section(row).course.cohort.designator, 'bio')

    def test_pattern_accepts_names_without_a_space(self):
        rows = [self.row(course_name=name)
                for name in ('ARDE2430', 'COMM 1030-01', 'bio101')]
        with knob('COURSE_NAME_PATTERN', self.PATTERN):
            result = self.run_import(*rows)
        self.assertEqual(result['summary']['successful'], 3)
        self.assertEqual(self.section(rows[0]).course.cohort.designator, 'ARDE')
        self.assertEqual(self.section(rows[1]).course.cohort.designator, 'COMM')
        self.assertEqual(self.section(rows[2]).course.cohort.designator, 'BIO')

    def test_pattern_rejects_a_new_course_that_does_not_match(self):
        with knob('COURSE_NAME_PATTERN', self.PATTERN):
            result = self.run_import(self.row(course_name='intro to bio'))
        self.assertEqual(result['summary']['failed'], 1)
        self.assertIn('course name pattern', result['records'][0]['RESULT'])

    def test_pattern_lets_an_existing_course_through(self):
        cohort = Cohort.objects.create(name='X', designator='X')
        Course.objects.create(name='Odd Name', title='Odd', cohort=cohort)
        row = self.row(course_name='Odd Name')
        with knob('COURSE_NAME_PATTERN', self.PATTERN):
            self.run_import(row)
        self.assertEqual(self.section(row).course.name, 'Odd Name')


class RowSchemaTests(ClassSectionKnobTestBase):
    DATES = {
        'registration_start_date': '8/1/2026', 'registration_end_date': '2026-08-20',
        'payment_due_date': '09/15/2026', 'grade_due_date': '12/20/2026',
    }

    def test_default_schema(self):
        self.assertIs(class_section_row_schema(), ClassSectionRow)
        self.assertNotIn('payment_due_date', class_section_row_schema().csv_headers())

    def test_due_dates_on_create_and_update(self):
        row = self.row(**self.DATES)
        with knob('ROW_SCHEMA', DueDatesRow):
            self.assertIn('grade_due_date', class_section_row_schema().csv_headers())
            self.run_import(dict(row))
            section = self.section(row)
            self.assertEqual(section.registration_start_date, datetime.date(2026, 8, 1))
            self.assertEqual(section.registration_end_date, datetime.date(2026, 8, 20))
            self.assertEqual(section.payment_due_date, datetime.date(2026, 9, 15))
            self.assertEqual(section.grade_due_date, datetime.date(2026, 12, 20))

            for bulk in (True, False):
                self.run_import(dict(row, payment_due_date='10/1/2026'), bulk=bulk)
                self.assertEqual(self.section(row).payment_due_date,
                                 datetime.date(2026, 10, 1))
                row['payment_due_date'] = '09/15/2026'

    def test_schema_and_instructor_columns_combine(self):
        with knob('ROW_SCHEMA', DueDatesRow), knob('AUTO_CREATE_TEACHER', True):
            headers = class_section_row_schema().csv_headers()
        self.assertIn('grade_due_date', headers)
        self.assertIn('instructor_id', headers)

    def test_default_ignores_due_date_columns(self):
        row = self.row(**self.DATES)
        self.run_import(row)
        self.assertIsNone(self.section(row).payment_due_date)
