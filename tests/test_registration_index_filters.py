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
