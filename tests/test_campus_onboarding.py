"""MC-12 (#36): onboarding follows the campus the student applied on.

In multi-campus mode an application started on a campus's host is onboarded
for that campus's active term, and a login rolls over only the campuses the
student already has onboarding on -- each to its own active term, never the
campus of the host they logged in on. Single-campus mode is unchanged.
"""
import uuid

from django.conf import settings
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings

from cis.campus_context import campus_context
from cis.models.course import Campus
from cis.models.customuser import CustomUser
from cis.models.settings import Setting
from cis.models.student import Student
from cis.models.term import AcademicYear, Term
from cis.signals.onboarding import on_application_started, reseed_on_term_rollover
from student_onboarding.models import StudentOnboarding

KEY = f'{settings.CAMPUS_CODE_PREFIX}_cis_registrations'


def _campus(name):
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')


def _term(campus, code):
    year = AcademicYear.objects.create(name=f'AY-{uuid.uuid4().hex[:6]}', campus=campus)
    return Term.objects.create(academic_year=year, code=code, label=code)


@override_settings(MULTI_CAMPUS=True)
class MultiCampusOnboardingTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        self.c1 = _campus('C1')
        self.c2 = _campus('C2')
        self.t1 = _term(self.c1, 'C1-FA')
        self.t2 = _term(self.c2, 'C2-FA')
        for campus, term in ((self.c1, self.t1), (self.c2, self.t2)):
            Setting.objects.create(key=KEY, campus=campus, value={
                'active_term': str(term.id), 'registration_terms': [str(term.id)]})
        user = CustomUser.objects.create_user(
            username=f's{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')
        with campus_context(self.c1):
            self.student = Student.objects.create(user=user)

    def _terms(self):
        return set(StudentOnboarding.objects.filter(
            student=self.student).values_list('term__code', flat=True))

    def test_created_on_a_campus_host_is_onboarded_for_that_campus(self):
        self.assertEqual(self._terms(), {'C1-FA'})

    def test_application_started_uses_the_host_campus_term(self):
        with campus_context(self.c2):
            on_application_started(self.student)
        self.assertIn('C2-FA', self._terms())

    def test_login_rolls_over_only_the_students_campuses(self):
        new_t1 = _term(self.c1, 'C1-SP')
        Setting.objects.filter(key=KEY, campus=self.c1).update(value={
            'active_term': str(new_t1.id), 'registration_terms': [str(new_t1.id)]})
        request = RequestFactory().get('/')
        # Logging in on c2's host must not start c2 onboarding.
        with campus_context(self.c2):
            reseed_on_term_rollover(sender=None, request=request, user=self.student.user)
        self.assertEqual(self._terms(), {'C1-FA', 'C1-SP'})

    def test_created_without_a_campus_skips_seeding(self):
        user = CustomUser.objects.create_user(
            username=f's{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')
        student = Student.objects.create(user=user)  # no campus context
        self.assertFalse(StudentOnboarding.objects.filter(student=student).exists())
