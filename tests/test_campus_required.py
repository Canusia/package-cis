"""MC-09 (#33): campus-owned records must have a campus in multi-campus mode.

Course, ClassSection and AcademicYear saved without a campus take the campus
the code is serving (the request host's, or --campus for a command); with no
campus in context either, the save is refused. Single-campus mode is
unchanged: a null campus still means "shared".
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from cis.campus_context import campus_context
from cis.models.course import Campus, Cohort, Course
from cis.models.section import ClassSection
from cis.models.term import AcademicYear, Term


def _campus(name):
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')


class SingleCampusUnchangedTests(TestCase):
    def test_null_campus_is_still_allowed(self):
        year = AcademicYear.objects.create(name=f'Y{uuid.uuid4().hex[:6]}')
        self.assertIsNone(year.campus)


@override_settings(MULTI_CAMPUS=True)
class MultiCampusRequiredTests(TestCase):
    def setUp(self):
        self.c1 = _campus('C1')
        self.cohort = Cohort.objects.create(name='English', designator='ENGL', campus=self.c1)

    def test_missing_campus_is_refused_outside_a_campus_context(self):
        with self.assertRaises(ValidationError):
            AcademicYear.objects.create(name='2026-2027')
        with self.assertRaises(ValidationError):
            Course.objects.create(catalog_number='101', title='A', cohort=self.cohort)

    def test_missing_campus_is_taken_from_the_context(self):
        with campus_context(self.c1):
            year = AcademicYear.objects.create(name='2026-2027')
            course = Course.objects.create(catalog_number='101', title='A', cohort=self.cohort)
            term = Term.objects.create(academic_year=year, code='F26', label='Fall')
            section = ClassSection.objects.create(course=course, term=term, class_number='1')
        self.assertEqual(year.campus, self.c1)
        self.assertEqual(course.campus, self.c1)
        self.assertEqual(section.campus, self.c1)

    def test_explicit_campus_is_kept(self):
        c2 = _campus('C2')
        with campus_context(self.c1):
            year = AcademicYear.objects.create(name='2026-2027', campus=c2)
        self.assertEqual(year.campus, c2)
