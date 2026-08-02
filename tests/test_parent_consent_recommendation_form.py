"""Regression tests for the public parent-consent page (compliance.parent_consent).

Bug: StudentRecommendationForm.__init__(self, student, current_registrations, ...)
requires `student`, but the GET-path instantiation at
webapp/student/views/compliance.py:414 omitted it, raising
`TypeError: ... missing 1 required positional argument: 'student'`
and 500-ing the public page (AnonymousUser).
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.student import Student
from cis.forms.student import StudentRecommendationForm

User = get_user_model()


class StudentRecommendationFormConstructionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler blows up in tests
        # because the request has no usable IP. Disconnect for the duration
        # of this test case (mirrors test_teacher_course_viewset_filters.py).
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    @classmethod
    def setUpTestData(cls):
        # Student.save() assigns the user to the 'student' group.
        Group.objects.get_or_create(name='student')
        cls.user = User.objects.create_user(
            username='parent_consent_stu',
            email='parent_consent_stu@example.com',
            password='x', first_name='Stu', last_name='Dent',
        )
        cls.student = Student.objects.create(
            user=cls.user, graduation_year=2027,
        )

    def test_form_constructs_with_student_and_registrations(self):
        # Mirrors the fixed call at compliance.py:414. With the bug present
        # (student omitted) this raises TypeError; with the fix it builds.
        form = StudentRecommendationForm(
            self.student,
            current_registrations=[],
            initial={
                'student': self.student.id,
                'term': None,
                'student_state_id': self.student.state_id,
            },
        )
        self.assertIsNotNone(form)
        # __init__ seeds the grade-level field from student.get_grade_level().
        self.assertEqual(
            form.fields['student_grade_level'].initial,
            self.student.get_grade_level(),
        )


from django.test import Client
from django.conf import settings as django_settings

from cis.models.term import AcademicYear, Term
from cis.models.course import Course, Cohort
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting


class ParentConsentPublicPageTests(TestCase):
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

    @classmethod
    def setUpTestData(cls):
        # Student.save() assigns the user to the 'student' group.
        Group.objects.get_or_create(name='student')
        # StudentRegistration's post_save signal calls student.add_note(), which
        # falls back to the 'cron' system user when no request user is present.
        User.objects.get_or_create(
            username='cron',
            defaults={'email': 'cron@example.com'},
        )
        cls.user = User.objects.create_user(
            username='pc_http_stu', email='pc_http_stu@example.com',
            password='x', first_name='Stu', last_name='Http',
        )
        cls.student = Student.objects.create(
            user=cls.user, graduation_year=2027,
        )

        cls.academic_year = AcademicYear.objects.create(name='2026-2027')
        cls.term = Term.objects.create(
            academic_year=cls.academic_year, code='2027SP', label='Spring 2027',
        )

        cls.cohort = Cohort.objects.create(name='PC Cohort', designator='PCC')
        cls.course = Course.objects.create(
            catalog_number='101', title='Intro', name='INTRO',
            cohort=cls.cohort, credit_hours=3,
        )
        cls.section = ClassSection.objects.create(
            term=cls.term, course=cls.course,
            class_number='10101', section_number='001',
        )
        # An 'applied' registration in a registration term is what drives the
        # GET loop in parent_consent past the `continue` (line 392) and into
        # the StudentRecommendationForm instantiation at line 414.
        cls.registration = StudentRegistration.objects.create(
            student=cls.student, class_section=cls.section, status='applied',
            status_changed_on={},
        )

        # registration_terms() reads this Setting; without it the loop never
        # runs and line 414 is never reached.
        key = django_settings.CAMPUS_CODE_PREFIX + '_cis_registrations'
        Setting.objects.update_or_create(
            key=key,
            defaults={'value': {'registration_terms': [str(cls.term.id)]}},
        )

    def test_public_get_renders_200(self):
        client = Client(REMOTE_ADDR='127.0.0.1')  # AnonymousUser, no login
        url = f'/student/parent/{self.student.id}/{self.term.id}'
        resp = client.get(url, follow=True)
        # Before the fix this 500s with TypeError; after the fix it renders.
        self.assertEqual(resp.status_code, 200)
