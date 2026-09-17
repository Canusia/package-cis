"""The /ce/students/ "By Status" filters, and the one that lied.

"Not Applied for Class" was implemented as two consecutive
`if record_type == 'not_applied'` blocks. The first selected students with no
registration; the second then narrowed to account_verified=False. So the filter
returned only UNVERIFIED students and silently dropped every verified student
who had signed up but not yet applied for a class -- the exact population
admins were using it to find.
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, RequestFactory

from cis.models.course import Campus, Cohort, Course
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.term import AcademicYear, Term
from cis.views.student import StudentViewSet

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class RecordTypeFilterTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(
            username='cron', defaults={'email': 'cron@x.com'})

        self.ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.term = Term.objects.create(
            academic_year=self.ay, code=f'FA{_sfx()[:4]}', label=f'Fall-{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.campus = Campus.objects.create(
            name=f'C-{_sfx()}', code=f'C-{_sfx()}')
        self.course = Course.objects.create(
            catalog_number='101', title='A', cohort=self.cohort,
            campus=self.campus)
        self.section = ClassSection.objects.create(
            class_number='1001', term=self.term, course=self.course)

        # the four states that matter for this filter
        self.unverified_no_reg = self._student(verified=False)
        self.verified_no_reg = self._student(verified=True)
        self.unverified_with_reg = self._student(verified=False)
        self.verified_with_reg = self._student(verified=True)
        for student in (self.unverified_with_reg, self.verified_with_reg):
            StudentRegistration.objects.create(
                student=student, class_section=self.section,
                status_changed_on={'applied_on': '01/01/2024'})

        # Superuser AND in 'ce': get_queryset() returns none() for a user with
        # no recognised role, and superuser bypasses campus scoping so these
        # tests isolate the record_type filters.
        self.user = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])

    def _student(self, verified):
        user = User.objects.create_user(
            username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        return Student.objects.create(user=user, account_verified=verified)

    def _filter(self, record_type):
        request = RequestFactory().get('/ce/api/student', {
            'record_type': record_type, 'format': 'datatables'})
        request.user = self.user
        view = StudentViewSet()
        view.request = request
        return view.get_queryset()

    # --- the bug -------------------------------------------------------------

    def test_not_applied_includes_verified_students(self):
        # The regression: a verified student who has not applied for a class was
        # dropped by a second, shadowing filter block.
        self.assertIn(self.verified_no_reg, self._filter('not_applied'))

    def test_not_applied_includes_unverified_students(self):
        self.assertIn(self.unverified_no_reg, self._filter('not_applied'))

    def test_not_applied_excludes_students_with_a_registration(self):
        qs = self._filter('not_applied')
        self.assertNotIn(self.verified_with_reg, qs)
        self.assertNotIn(self.unverified_with_reg, qs)

    def test_not_applied_returns_each_student_once(self):
        ids = [s.id for s in self._filter('not_applied')]
        self.assertEqual(len(ids), len(set(ids)))

    # --- neighbouring filters must keep their own meaning --------------------

    def test_not_verified_is_still_account_verified_false(self):
        qs = self._filter('not_verified')
        self.assertIn(self.unverified_no_reg, qs)
        self.assertIn(self.unverified_with_reg, qs)
        self.assertNotIn(self.verified_no_reg, qs)
        self.assertNotIn(self.verified_with_reg, qs)

    def test_status_draft_filters_on_application_status(self):
        # draft is the marker for a signup that never completed: at EWU 308 of
        # the 310 draft students had no onboarding row.
        self.verified_no_reg.application_status = 'draft'
        self.verified_no_reg.save()
        self.verified_with_reg.application_status = 'accepted'
        self.verified_with_reg.save()
        qs = self._filter('status_draft')
        self.assertIn(self.verified_no_reg, qs)
        self.assertNotIn(self.verified_with_reg, qs)

    def test_empty_record_type_filters_nothing(self):
        qs = self._filter('')
        for student in (self.unverified_no_reg, self.verified_no_reg,
                        self.unverified_with_reg, self.verified_with_reg):
            self.assertIn(student, qs)
