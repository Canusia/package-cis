"""The class-section feed's high-school filter can be replaced by a tenant
(#87): services/section_visibility.py sections_for_highschool(records, *,
highschool_id, cte_id, request). Without it the filter is unchanged. Also the
section due-date filters (#86)."""
from datetime import timedelta
from unittest import mock

from django.test import RequestFactory, TestCase
from django.utils import timezone

from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection
from cis.models.term import AcademicYear, Term
from cis.tests.test_class_section_viewset_scoping import _suffix, _user_in_group


class ClassSectionFeedFixture(TestCase):
    def setUp(self):
        ay = AcademicYear.objects.create(name=f'AY-{_suffix()}')
        self.term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_suffix()}')
        cohort = Cohort.objects.create(name=f'Co-{_suffix()}', designator='CO')
        course = Course.objects.create(catalog_number='101', title='Intro', cohort=cohort)
        self.hs_a = HighSchool.objects.create(name=f'HS-A-{_suffix()}')
        self.hs_b = HighSchool.objects.create(name=f'HS-B-{_suffix()}')
        self.section_a = ClassSection.objects.create(
            term=self.term, course=course, highschool=self.hs_a)
        self.section_b = ClassSection.objects.create(
            term=self.term, course=course, highschool=self.hs_b)
        self.ce_user = _user_in_group('ce')

    def _ids(self, **params):
        from cis.views.section import ClassSectionViewSet
        vs = ClassSectionViewSet()
        request = RequestFactory().get('/', {'term': str(self.term.id), **params})
        request.user = self.ce_user
        vs.request = request
        return {r.id for r in vs.get_queryset()}


class SectionVisibilitySeamTests(ClassSectionFeedFixture):
    def test_default_filter_is_the_one_school(self):
        with mock.patch('cis.views.section.get_tenant_override', return_value=None):
            ids = self._ids(highschool_id=str(self.hs_a.id))
        self.assertEqual(ids, {self.section_a.id})

    def test_tenant_hook_decides_visibility(self):
        seen = {}

        def sections_for_highschool(records, *, highschool_id, cte_id, request):
            seen.update(highschool_id=highschool_id, cte_id=cte_id)
            return records.filter(highschool__in=[self.hs_a, self.hs_b])

        def override(module, attr):
            if (module, attr) == ('section_visibility', 'sections_for_highschool'):
                return sections_for_highschool
            return None

        with mock.patch('cis.views.section.get_tenant_override', override):
            ids = self._ids(highschool_id=str(self.hs_a.id))
        self.assertEqual(ids, {self.section_a.id, self.section_b.id})
        self.assertEqual(seen, {'highschool_id': str(self.hs_a.id), 'cte_id': None})


class SectionDueDateFilterTests(ClassSectionFeedFixture):
    def test_registration_window_overlap(self):
        ClassSection.objects.filter(pk=self.section_a.pk).update(
            registration_start_date='2026-08-01', registration_end_date='2026-08-31')
        ClassSection.objects.filter(pk=self.section_b.pk).update(
            registration_start_date='2026-10-01', registration_end_date='2026-10-31')
        self.assertEqual(
            self._ids(registration_open_start='2026-08-15', registration_open_end='2026-09-15'),
            {self.section_a.id})

    def test_bad_date_is_ignored(self):
        self.assertEqual(self._ids(registration_open_start='2026-13-45'),
                         {self.section_a.id, self.section_b.id})

    def test_grade_due_within_a_week(self):
        today = timezone.localdate()
        ClassSection.objects.filter(pk=self.section_a.pk).update(
            grade_due_date=today + timedelta(days=3))
        ClassSection.objects.filter(pk=self.section_b.pk).update(
            grade_due_date=today + timedelta(days=20))
        self.assertEqual(self._ids(grade_due_within='1w'), {self.section_a.id})
        self.assertEqual(self._ids(grade_due_within='1m'),
                         {self.section_a.id, self.section_b.id})
