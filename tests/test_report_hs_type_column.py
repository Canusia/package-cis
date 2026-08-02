"""School Type column on the High Schools / Classes category reports.

get_field() swallows a bad attribute path and returns '' rather than raising,
so a typo in one of these dotted keys would ship a permanently blank column.
These tests resolve each report's exact key against real objects.
"""
from django.test import TestCase

from cis.models.course import Campus, Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection
from cis.models.term import AcademicYear, Term
from cis.utils import get_field

SCHOOL_TYPE_LABEL = 'School Type'


class ReportFieldMapTests(TestCase):
    """Every report in these categories must carry the column."""

    def _fields_of(self, module_name, attr='datasource_fields'):
        import importlib
        module = importlib.import_module(f'cis.reports.{module_name}')
        return getattr(getattr(module, module_name), attr)

    def test_datasource_reports_expose_school_type(self):
        for name in ('highschool_admin_export', 'class_roster'):
            with self.subTest(report=name):
                self.assertIn('SchoolType', self._fields_of(name))


class ReportFieldResolutionTests(TestCase):
    def setUp(self):
        self.hs = HighSchool.objects.create(
            name='Zoned HS', code='ZON01', hs_type=['zone_a', 'zone_b'])

    def test_highschool_rooted_path_resolves(self):
        """teacher_password_reset / highschool_admin_* / started_future_classes
        all reach the school as `highschool.…`."""
        class Row:
            highschool = self.hs

        self.assertEqual(get_field(Row(), 'highschool.hs_type_display'),
                         'Zone A, Zone B')

    def test_class_section_rooted_path_resolves(self):
        """class_roster reaches it as `class_section.highschool.…`."""
        campus = Campus.objects.create(name='Main C', code='MAINC')
        year = AcademicYear.objects.create(name='2027-2028', campus=campus)
        term = Term.objects.create(academic_year=year, code='TRM1', label='T1')
        cohort = Cohort.objects.create(designator='CH', name='Cohort')
        course = Course.objects.create(cohort=cohort, catalog_number='101',
                                       name='C 101', title='Course 101',
                                       campus=campus)
        section = ClassSection.objects.create(
            course=course, term=term, highschool=self.hs)

        class Row:
            class_section = section

        self.assertEqual(
            get_field(Row(), 'class_section.highschool.hs_type_display'),
            'Zone A, Zone B')

    def test_untyped_school_yields_blank_not_an_error(self):
        plain = HighSchool.objects.create(name='Plain HS', code='PLN01')

        class Row:
            highschool = plain

        self.assertEqual(get_field(Row(), 'highschool.hs_type_display'), '')

    def test_a_bad_path_would_be_silently_blank(self):
        """Documents why the tests above matter: get_field never raises."""
        class Row:
            highschool = self.hs

        self.assertEqual(get_field(Row(), 'highschool.hs_type_typo'), '')
