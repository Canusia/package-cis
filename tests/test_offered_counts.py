"""Term and academic-year offering counts leave out cancelled sections
(#114 item 9), so a term full of cancelled sections doesn't look offered."""
import uuid

from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from cis.models import CustomUser
from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection
from cis.models.term import AcademicYear, Term


class OfferedCountTests(TestCase):
    def setUp(self):
        sfx = uuid.uuid4().hex[:6]
        self.ay = AcademicYear.objects.create(name=f'AY-{sfx}')
        self.term = Term.objects.create(academic_year=self.ay, code=sfx, label='Fall')
        cohort = Cohort.objects.create(name=f'Co-{sfx}', designator='CO')
        course_a = Course.objects.create(catalog_number='101', title='A', cohort=cohort)
        course_b = Course.objects.create(catalog_number='102', title='B', cohort=cohort)
        hs_a = HighSchool.objects.create(name=f'A-{sfx}')
        hs_b = HighSchool.objects.create(name=f'B-{sfx}')
        ClassSection.objects.create(term=self.term, course=course_a, highschool=hs_a, status='A')
        ClassSection.objects.create(term=self.term, course=course_b, highschool=hs_b, status='C')
        self.user = CustomUser.objects.create_superuser(
            username=f'su_{sfx}', email=f'su_{sfx}@x.com', password='x')

    def _row(self, viewset_class, pk):
        vs = viewset_class()
        vs.request = RequestFactory().get('/')
        vs.request.user = self.user
        vs.request.query_params = vs.request.GET
        vs.format_kwarg = None
        return vs.get_queryset().get(pk=pk)

    def _assert_counts(self, row):
        self.assertEqual(
            (row.num_sections, row.num_highschools, row.num_courses), (1, 1, 1))

    def test_term_counts(self):
        from cis.views.term import TermViewSet
        self._assert_counts(self._row(TermViewSet, self.term.pk))

    def test_academic_year_counts(self):
        from cis.views.academic_year import AcademicYearViewSet
        self._assert_counts(self._row(AcademicYearViewSet, self.ay.pk))

    def test_a_term_with_only_cancelled_sections_counts_zero(self):
        from cis.views.term import TermViewSet
        ClassSection.objects.filter(term=self.term).update(status='C')
        self.assertEqual(self._row(TermViewSet, self.term.pk).num_sections, 0)
