"""PT-1 regression: the /ce/api/student/ term_id filter must use the ORM
(parameterized) and reject non-UUID input, not interpolate raw SQL.

StudentViewSet.get_queryset previously built the term_id filter via
Student.objects.raw(f"... term_id = '{term_id}'"), which the pentest report
(pentest-report-2899.pdf, PT-1) exploited with a pg_sleep time-based payload.
These tests pin the safe behavior.
"""
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from cis.models import CustomUser
from cis.models.student import Student
from cis.models.section import ClassSection, StudentRegistration
from cis.models.course import Course, Cohort
from cis.models.term import Term, AcademicYear


class StudentViewSetTermFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Student.save() does Group.objects.get(name='student') unconditionally.
        Group.objects.get_or_create(name='student')
        # StudentViewSet.get_queryset (PT-4) scopes by role off request.user, so
        # this term-filter probe runs as a 'ce' user (full multi-tenant access).
        ce_group, _ = Group.objects.get_or_create(name='ce')
        cls.ce_user = get_user_model().objects.create_user(
            username='ce_termfilter', email='ce_termfilter@example.com',
            password='x')
        cls.ce_user.groups.add(ce_group)
        # StudentRegistration post_save -> add_note() falls back to the 'cron'
        # user when there is no bound request user (true in these tests).
        CustomUser.objects.create_user(
            username='cron', email='cron@example.com', password='x')

        academic_year = AcademicYear.objects.create(name='2025-2026')
        cls.term = Term.objects.create(
            label='Fall 2025', code='F25', academic_year=academic_year)
        cls.other_term = Term.objects.create(
            label='Spring 2026', code='S26', academic_year=academic_year)

        cohort = Cohort.objects.create(name='Test Cohort', designator='TST')
        course = Course.objects.create(
            catalog_number='101', title='SQLi Test', name='SQLI101',
            cohort=cohort)

        section = ClassSection.objects.create(
            course=course, term=cls.term,
            class_number=99801, section_number='001')
        other_section = ClassSection.objects.create(
            course=course, term=cls.other_term,
            class_number=99802, section_number='002')

        in_user = CustomUser.objects.create_user(
            username='in_term_stud', email='in_term@example.com', password='x')
        out_user = CustomUser.objects.create_user(
            username='out_term_stud', email='out_term@example.com', password='x')
        cls.in_term_student = Student.objects.create(user=in_user)
        cls.out_term_student = Student.objects.create(user=out_user)

        StudentRegistration.objects.create(
            student=cls.in_term_student, class_section=section,
            status_changed_on={})
        StudentRegistration.objects.create(
            student=cls.out_term_student, class_section=other_section,
            status_changed_on={})

    def _qs(self, **params):
        from cis.views.student import StudentViewSet
        vs = StudentViewSet()
        req = RequestFactory().get('/', params)
        req.user = self.ce_user
        vs.request = req
        return vs.get_queryset()

    def test_term_id_filters_to_students_registered_in_that_term(self):
        ids = [r.id for r in self._qs(term_id=str(self.term.id))]
        self.assertIn(self.in_term_student.id, ids)
        self.assertNotIn(self.out_term_student.id, ids)

    def test_sql_injection_payload_returns_empty_and_does_not_raise(self):
        payload = (
            "11111111-1111-1111-1111-111111111111' "
            "OR EXISTS(SELECT 1 FROM pg_sleep(5))) -- "
        )
        rows = list(self._qs(term_id=payload))
        self.assertEqual(rows, [])

    def test_non_uuid_term_id_returns_empty(self):
        rows = list(self._qs(term_id='not-a-uuid'))
        self.assertEqual(rows, [])
