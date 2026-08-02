"""Regression: instructor update_registration_status must not 500 on a
non-UUID `id` (or `section_id`) GET param.

Bug: GET /instructor/update_registration_status/?status=enrolled&id=abc&...
coerced 'abc' into the StudentRegistration UUID primary key inside
get_object_or_404, raising django.core.exceptions.ValidationError
('"abc" is not a valid UUID.') -> unhandled -> HTTP 500.

Fix mirrors the shipped PT-1 idiom: validate with uuid.UUID(str(value))
before the lookup; a malformed id yields a clean 404 (identical to a
well-formed-but-missing id, which get_object_or_404 already returns).
"""
import uuid

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher
from cis.models.student import Student
from cis.models.section import ClassSection, StudentRegistration
from cis.models.term import AcademicYear, Term
from cis.models.course import Cohort, Course

User = get_user_model()

URL = '/instructor/update_registration_status/'


class InstructorUpdateRegStatusUUIDGuardTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler blows up in tests
        # (no usable request IP). Disconnect for the duration of this case.
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
        Group.objects.get_or_create(name='instructor')
        Group.objects.get_or_create(name='student')

        # StudentRegistration's post_save signal calls student.add_note(),
        # which falls back to the 'cron' user when no request user is present.
        User.objects.create_user(
            username='cron', email='cron@example.com', password='x',
        )

        # The instructor we log in as.
        instructor_user = User.objects.create_user(
            username='instr_uuidguard', email='instr_uuidguard@example.com',
            password='x', first_name='In', last_name='Structor',
        )
        instructor_user.groups.add(Group.objects.get(name='instructor'))
        cls.instructor_user = instructor_user
        cls.teacher = Teacher.objects.create(user=instructor_user)

        cls.hs = HighSchool.objects.create(name='HS Guard')

        # A student + a section taught by this instructor + a registration.
        student_user = User.objects.create_user(
            username='stu_uuidguard', email='stu_uuidguard@example.com',
            password='x', first_name='Stu', last_name='Dent',
        )
        cls.student = Student.objects.create(
            user=student_user, highschool=cls.hs,
        )
        academic_year = AcademicYear.objects.create(name='2025-2026')
        term = Term.objects.create(
            academic_year=academic_year, code='FA25', label='Fall 2025',
        )
        cohort = Cohort.objects.create(name='Cohort Guard', designator='CG')
        course = Course.objects.create(
            catalog_number='101', title='Guard Course', cohort=cohort,
        )
        cls.section = ClassSection.objects.create(
            teacher=cls.teacher, highschool=cls.hs, term=term, course=course,
        )
        cls.registration = StudentRegistration.objects.create(
            student=cls.student, class_section=cls.section, highschool=cls.hs,
            status_changed_on={},
        )

    def setUp(self):
        self.client.force_login(self.instructor_user)

    def test_non_uuid_id_does_not_500(self):
        """The reported case: id='abc' must NOT raise -> not a 500."""
        resp = self.client.get(URL, {
            'status': 'enrolled',
            'id': 'abc',
            'section_id': str(self.section.id),
        })
        self.assertNotEqual(resp.status_code, 500)
        # Clean not-found, matching a well-formed-but-missing id.
        self.assertEqual(resp.status_code, 404)

    def test_well_formed_missing_uuid_id_is_404(self):
        """A valid-format but nonexistent id is a clean 404 (baseline)."""
        resp = self.client.get(URL, {
            'status': 'enrolled',
            'id': str(uuid.uuid4()),
            'section_id': str(self.section.id),
        })
        self.assertNotEqual(resp.status_code, 500)
        self.assertEqual(resp.status_code, 404)

    def test_malformed_id_and_missing_uuid_id_respond_identically(self):
        """Malformed and missing ids must be indistinguishable to the client."""
        bad = self.client.get(URL, {
            'status': 'enrolled', 'id': 'abc',
            'section_id': str(self.section.id),
        })
        missing = self.client.get(URL, {
            'status': 'enrolled', 'id': str(uuid.uuid4()),
            'section_id': str(self.section.id),
        })
        self.assertEqual(bad.status_code, missing.status_code)

    def test_valid_registration_reaches_normal_path(self):
        """A real registration + matching section -> success JSON (200)."""
        resp = self.client.get(URL, {
            'status': 'enrolled',
            'id': str(self.registration.id),
            'section_id': str(self.section.id),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'success')
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.verification_status, 'enrolled')

    def test_non_uuid_section_id_is_clean_401(self):
        """A real id with a non-UUID section_id -> existing 401 mismatch path,
        never a 500."""
        resp = self.client.get(URL, {
            'status': 'enrolled',
            'id': str(self.registration.id),
            'section_id': 'abc',
        })
        self.assertNotEqual(resp.status_code, 500)
        self.assertEqual(resp.status_code, 401)
