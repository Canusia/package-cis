"""Campus gate for the student_profile_dynamic_export report: a ce requester's
export only includes students who applied at their processable campuses (via
studentregistration -> class_section -> course -> campus), optionally narrowed
to a selected campus. Superusers are unscoped.
"""
import datetime
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase, RequestFactory
from django.utils import timezone

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.term import AcademicYear, Term
from cis.models.course import Campus, Cohort, Course
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.reports.student_profile_dynamic_export import student_profile_dynamic_export

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class StudentProfileDynamicExportCampusTests(TestCase):
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
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@x.com'})

        self.ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.term = Term.objects.create(
            academic_year=self.ay, code='FA', label=f'Fall-{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.course_a = Course.objects.create(
            catalog_number='101', title='A', cohort=self.cohort, campus=self.campus_a)
        self.course_b = Course.objects.create(
            catalog_number='102', title='B', cohort=self.cohort, campus=self.campus_b)
        self.sec_a = ClassSection.objects.create(
            class_number='1001', term=self.term, course=self.course_a)
        self.sec_b = ClassSection.objects.create(
            class_number='1002', term=self.term, course=self.course_b)

        now = timezone.now()
        self.student_a = self._registered_student(self.sec_a, now)
        self.student_b = self._registered_student(self.sec_b, now)

        self.ce = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.ce.campus = {'process_campus': [str(self.campus_a.id)]}
        self.ce.save()
        self.superuser = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')

        self.created_on = (now - datetime.timedelta(days=1)).date()
        self.created_until = (now + datetime.timedelta(days=1)).date()

    def _registered_student(self, section, created_at):
        u = User.objects.create_user(
            username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        User.objects.filter(pk=u.pk).update(created_at=created_at)
        u.refresh_from_db()
        student = Student.objects.create(user=u, account_verified=True)
        StudentRegistration.objects.create(
            student=student, class_section=section, status='applied',
            status_changed_on={'applied_on': '01/01/2024'})
        return student

    def _data(self, campus):
        return {
            'created_on': self.created_on,
            'created_until': self.created_until,
            'campus': campus,
        }

    def test_campus_field_is_required_multiselect_of_accessible(self):
        from django import forms as dj_forms
        req = RequestFactory().get('/')
        req.user = self.ce
        form = student_profile_dynamic_export(req)
        # campus is the FIRST field, required, and a multi-select.
        self.assertEqual(list(form.fields)[0], 'campus')
        self.assertIsInstance(
            form.fields['campus'], dj_forms.ModelMultipleChoiceField)
        self.assertTrue(form.fields['campus'].required)
        qs = form.fields['campus'].queryset
        self.assertIn(self.campus_a, qs)
        self.assertNotIn(self.campus_b, qs)

    def test_ce_result_scoped_to_selected_own_campus(self):
        report = student_profile_dynamic_export()
        qs = report.get_result(
            self._data(campus=[str(self.campus_a.id)]), user=self.ce)
        self.assertIn(self.student_a, qs)
        self.assertNotIn(self.student_b, qs)

    def test_ce_cannot_widen_to_inaccessible_campus(self):
        # selecting A (accessible) + B (not) keeps only A's students.
        report = student_profile_dynamic_export()
        qs = report.get_result(
            self._data(campus=[str(self.campus_a.id), str(self.campus_b.id)]),
            user=self.ce)
        self.assertIn(self.student_a, qs)
        self.assertNotIn(self.student_b, qs)

    def test_ce_only_inaccessible_selection_returns_none(self):
        report = student_profile_dynamic_export()
        qs = report.get_result(
            self._data(campus=[str(self.campus_b.id)]), user=self.ce)
        self.assertNotIn(self.student_a, qs)
        self.assertNotIn(self.student_b, qs)

    def test_superuser_uses_selection_as_is(self):
        report = student_profile_dynamic_export()
        qs = report.get_result(
            self._data(campus=[str(self.campus_b.id)]), user=self.superuser)
        self.assertIn(self.student_b, qs)
        self.assertNotIn(self.student_a, qs)
