"""/ce/api/class_section/?course_administrator_user_id=<id> returns only
sections whose course has an Active CourseAdministrator row for that user.
Critically: a user administering nothing gets ZERO rows, not every section.

EWU has no test factories, so fixtures are built with direct
Model.objects.create() following cis/tests/test_class_section_viewset_scoping.py.
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, RequestFactory

from cis.models.term import AcademicYear, Term
from cis.models.highschool import HighSchool
from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.section import ClassSection
from cis.views.section import ClassSectionViewSet

User = get_user_model()


def _suffix():
    return uuid.uuid4().hex[:8]


def _ce_user():
    sfx = _suffix()
    user = User.objects.create_user(
        username=f'ce_{sfx}', email=f'ce_{sfx}@example.com', password='x')
    group, _ = Group.objects.get_or_create(name='ce')
    user.groups.add(group)
    return user


def _plain_user():
    sfx = _suffix()
    return User.objects.create_user(
        username=f'u_{sfx}', email=f'u_{sfx}@example.com', password='x')


def _queryset_for(user, **params):
    request = RequestFactory().get('/ce/api/class_section/', params)
    request.user = user
    viewset = ClassSectionViewSet()
    viewset.request = request
    return viewset.get_queryset()


class CourseAdministratorSectionFilterTests(TestCase):
    def setUp(self):
        self.staff = _ce_user()
        self.admin_user = _plain_user()

        self.ay = AcademicYear.objects.create(name=f'AY-{_suffix()}')
        self.term = Term.objects.create(
            academic_year=self.ay, code='FA', label=f'Fall-{_suffix()}')
        self.cohort = Cohort.objects.create(name=f'Co-{_suffix()}', designator='CO')
        self.hs = HighSchool.objects.create(name=f'HS-{_suffix()}')

        self.my_course = Course.objects.create(
            catalog_number='101', title='Mine', cohort=self.cohort)
        self.other_course = Course.objects.create(
            catalog_number='201', title='Other', cohort=self.cohort)

        CourseAdministrator.objects.create(
            course=self.my_course, user=self.admin_user, status='Active')

        self.my_section = ClassSection.objects.create(
            term=self.term, course=self.my_course, highschool=self.hs)
        self.other_section = ClassSection.objects.create(
            term=self.term, course=self.other_course, highschool=self.hs)

    def test_returns_only_sections_for_administered_courses(self):
        qs = _queryset_for(
            self.staff, term='-1',
            course_administrator_user_id=str(self.admin_user.id))
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.my_section.id, ids)
        self.assertNotIn(self.other_section.id, ids)

    def test_inactive_administrator_row_is_excluded(self):
        CourseAdministrator.objects.filter(
            user=self.admin_user).update(status='Inactive')
        qs = _queryset_for(
            self.staff, term='-1',
            course_administrator_user_id=str(self.admin_user.id))
        self.assertEqual(qs.count(), 0)

    def test_user_administering_nothing_gets_zero_rows(self):
        nobody = _plain_user()
        qs = _queryset_for(
            self.staff, term='-1',
            course_administrator_user_id=str(nobody.id))
        self.assertEqual(qs.count(), 0)

    def test_non_integer_value_returns_empty_not_everything(self):
        qs = _queryset_for(
            self.staff, term='-1', course_administrator_user_id='not-a-number')
        self.assertEqual(qs.count(), 0)

    def test_admin_row_with_null_course_does_not_widen_results(self):
        CourseAdministrator.objects.create(
            course=None, user=self.admin_user, status='Active')
        qs = _queryset_for(
            self.staff, term='-1',
            course_administrator_user_id=str(self.admin_user.id))
        ids = set(qs.values_list('id', flat=True))
        self.assertEqual(ids, {self.my_section.id})

    def test_duplicate_admin_rows_do_not_duplicate_sections(self):
        CourseAdministrator.objects.create(
            course=self.my_course, user=self.admin_user,
            status='Active', role='Dean')
        qs = _queryset_for(
            self.staff, term='-1',
            course_administrator_user_id=str(self.admin_user.id))
        self.assertEqual(
            list(qs.values_list('id', flat=True)).count(self.my_section.id), 1)

    def test_absent_param_leaves_queryset_unfiltered(self):
        qs = _queryset_for(self.staff, term='-1')
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.my_section.id, ids)
        self.assertIn(self.other_section.id, ids)
