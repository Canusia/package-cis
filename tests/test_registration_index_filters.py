"""Registrations index filters.

#18: "With Prereqs" returned exactly the registrations whose course has *no*
     prerequisite.
#21: the Parent Consent filter was rendered with d-none on every tenant; it now
     shows only where the parent_consent onboarding step is enabled.
"""
import re
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIRequestFactory

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.term import AcademicYear, Term
from cis.views.registration import RegistrationViewSet

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class WithPrereqFilterTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@x.com'})
        # The feed and the page both admit only the ce group (superuser keeps
        # the campus scope out of the way).
        self.superuser = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')
        self.superuser.groups.add(Group.objects.get_or_create(name='ce')[0])

        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        with_prereq = Course.objects.create(
            catalog_number='201', title='With', cohort=cohort, prereq='MATH 101')
        blank_prereq = Course.objects.create(
            catalog_number='101', title='Blank', cohort=cohort, prereq='')
        null_prereq = Course.objects.create(
            catalog_number='102', title='Null', cohort=cohort, prereq=None)

        self.reg_with = self._registration(term, with_prereq)
        self.reg_blank = self._registration(term, blank_prereq)
        self.reg_null = self._registration(term, null_prereq)

    def _registration(self, term, course):
        section = ClassSection.objects.create(
            class_number=_sfx()[:6], term=term, course=course)
        user = User.objects.create_user(
            username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        student = Student.objects.create(user=user, account_verified=True)
        return StudentRegistration.objects.create(
            student=student, class_section=section,
            status_changed_on={'applied_on': '01/01/2024'})

    def _ids(self, **params):
        request = APIRequestFactory().get('/x', {'term': '-3', **params})
        request.user = self.superuser
        viewset = RegistrationViewSet()
        viewset.request = request
        return set(viewset.get_queryset().values_list('id', flat=True))

    def test_with_prereq_returns_only_courses_that_have_one(self):
        self.assertEqual(self._ids(record_type='with_prereq'), {self.reg_with.id})

    def test_without_the_filter_all_are_returned(self):
        self.assertTrue(
            {self.reg_with.id, self.reg_blank.id, self.reg_null.id} <= self._ids())


class ParentConsentFilterVisibilityTests(TestCase):
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
        # The feed and the page both admit only the ce group (superuser keeps
        # the campus scope out of the way).
        self.superuser = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')
        self.superuser.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.client.force_login(self.superuser)

    def _page(self, step):
        with mock.patch('student_onboarding.step_registry.get', return_value=step):
            return self.client.get(reverse('cis:registrations'))

    def test_hidden_when_parent_consent_step_disabled(self):
        resp = self._page(None)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'name="signed_parent_consent"')

    def test_shown_when_parent_consent_step_enabled(self):
        resp = self._page(object())
        self.assertEqual(resp.status_code, 200)
        match = re.search(
            r'<select class="([^"]*)"\s+name="signed_parent_consent"',
            resp.content.decode())
        self.assertIsNotNone(match)
        self.assertNotIn('d-none', match.group(1))


class HighSchoolFilterTests(TestCase):
    """#133: "By High School" on the Registrations index (ported from nnu)."""

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
        from cis.models.highschool import HighSchool
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@x.com'})
        self.superuser = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')
        self.superuser.groups.add(Group.objects.get_or_create(name='ce')[0])

        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.course = Course.objects.create(catalog_number='101', title='C', cohort=cohort)
        self.central = HighSchool.objects.create(name='Central High', code=_sfx()[:6])
        self.north = HighSchool.objects.create(name='North High', code=_sfx()[:6])
        self.no_sections = HighSchool.objects.create(name='Empty High', code=_sfx()[:6])

        self.reg_central = self._registration(self.central)
        self.reg_north = self._registration(self.north)
        self.reg_campus = self._registration(None)  # on-campus / online section

    def _registration(self, highschool):
        section = ClassSection.objects.create(
            class_number=_sfx()[:6], term=self.term, course=self.course,
            highschool=highschool)
        user = User.objects.create_user(
            username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        student = Student.objects.create(user=user, account_verified=True)
        return StudentRegistration.objects.create(
            student=student, class_section=section,
            status_changed_on={'applied_on': '01/01/2024'})

    def _ids(self, **params):
        request = APIRequestFactory().get('/x', {'term': '-3', **params})
        request.user = self.superuser
        viewset = RegistrationViewSet()
        viewset.request = request
        return set(viewset.get_queryset().values_list('id', flat=True))

    def test_filters_to_the_sections_high_school(self):
        self.assertEqual(self._ids(highschool=str(self.central.id)), {self.reg_central.id})

    def test_without_the_filter_sections_with_no_school_are_kept(self):
        self.assertTrue({self.reg_central.id, self.reg_north.id, self.reg_campus.id}
                        <= self._ids())

    def test_malformed_id_matches_nothing(self):
        self.assertEqual(self._ids(highschool='not-a-uuid'), set())

    def test_picker_lists_only_schools_that_host_sections(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse('cis:registrations'))
        self.assertEqual(resp.status_code, 200)
        names = [hs.name for hs in resp.context['highschools']]
        self.assertIn('Central High', names)
        self.assertIn('North High', names)
        self.assertNotIn('Empty High', names)
        self.assertEqual(names, sorted(names))
        self.assertContains(resp, 'name="highschool"')


class HighSchoolPickerCampusScopeTests(TestCase):
    """#133: on a multi-campus deployment a CE user's picker lists only the
    current campus's schools (superusers skip scope_highschools)."""

    def test_lists_only_schools_linked_to_the_current_campus(self):
        from django.conf import settings
        from django.test import override_settings
        from cis.campus_context import campus_context
        from cis.models.course import Campus
        from cis.models.highschool import HighSchool, HighSchoolCampus
        from cis.views.registration import _section_highschools

        prefix = settings.CAMPUS_CODE_PREFIX
        c1 = Campus.objects.create(name='C1', code=f'{prefix}-c1')
        c2 = Campus.objects.create(name='C2', code=f'{prefix}-c2')
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        course = Course.objects.create(catalog_number='101', title='C', cohort=cohort)
        schools = {}
        for name, campus in (('One High', c1), ('Two High', c2)):
            hs = HighSchool.objects.create(name=name, code=_sfx()[:6])
            HighSchoolCampus.objects.update_or_create(
                highschool=hs, campus=campus, defaults={'status': 'Active'})
            # The post_save signal may link a new school to another campus too.
            HighSchoolCampus.objects.filter(highschool=hs).exclude(campus=campus).delete()
            ClassSection.objects.create(
                class_number=_sfx()[:6], term=term, course=course, highschool=hs)
            schools[name] = hs
        ce = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        ce.groups.add(Group.objects.get_or_create(name='ce')[0])

        with override_settings(MULTI_CAMPUS=True), campus_context(c1):
            names = [hs.name for hs in _section_highschools(ce)]
        self.assertIn('One High', names)
        self.assertNotIn('Two High', names)


class ClassSectionSearchHighSchoolColumnTests(TestCase):
    """#133: the class section search shows each section's high school."""

    def test_template_has_a_null_safe_high_school_column(self):
        from django.template.loader import get_template
        source = get_template('cis/sections/class_section_search.html').template.source
        self.assertIn("data-name='highschool.name'", source)
        self.assertIn('row.highschool ? row.highschool.name', source)

    def test_datatables_feed_still_emits_the_high_school_name(self):
        from cis.serializers.tables import SlimClassSectionSerializer
        self.assertIn('name', SlimClassSectionSerializer().fields['highschool'].fields)
