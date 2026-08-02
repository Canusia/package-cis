"""Campus gate for the pending_future_classes_courses report: a ce requester's
export only includes teacher-course certificates at their processable campuses
(via course -> campus). Superusers are unscoped.
"""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase, RequestFactory

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.term import AcademicYear, Term
from cis.models.course import Campus, Cohort, Course
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate
from cis.models.highschool import HighSchool
from cis.models.settings import Setting
from cis.reports.pending_future_classes_courses import pending_future_classes_courses

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class PendingFutureClassesCoursesReportCampusTests(TestCase):
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
        Group.objects.get_or_create(name='instructor')
        Group.objects.get_or_create(name='student')

        # `fs_settings.from_db()` needs a value with course_status /
        # teacher_course_status, and both fixtures below must match it so
        # they'd normally appear in the report before campus scoping.
        Setting.objects.create(
            key='cis_future_sections',
            value={'course_status': ['Active'], 'teacher_course_status': ['Teaching']}
        )

        self.ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')

        self.course_a = Course.objects.create(
            catalog_number='101', title='A', cohort=self.cohort,
            campus=self.campus_a, status='Active')
        self.course_b = Course.objects.create(
            catalog_number='102', title='B', cohort=self.cohort,
            campus=self.campus_b, status='Active')

        self.highschool = HighSchool.objects.create(name=f'HS-{_sfx()}')

        self.cert_a = self._certificate(self.course_a)
        self.cert_b = self._certificate(self.course_b)

        self.ce = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.ce.campus = {'process_campus': [str(self.campus_a.id)]}
        self.ce.save()
        self.superuser = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')

    def _certificate(self, course):
        u = User.objects.create_user(
            username=f'tch_{_sfx()}', email=f'tch_{_sfx()}@x.com', password='x')
        teacher = Teacher.objects.create(user=u)
        teacher_hs = TeacherHighSchool.objects.create(
            teacher=teacher, highschool=self.highschool)
        return TeacherCourseCertificate.objects.create(
            teacher_highschool=teacher_hs, course=course, status='Teaching')

    def _data(self, campus):
        return {'academic_year': [str(self.ay.id)], 'campus': campus}

    def test_campus_field_is_required_multiselect_of_accessible(self):
        from django import forms as dj_forms
        req = RequestFactory().get('/')
        req.user = self.ce
        form = pending_future_classes_courses(req)
        # campus is the FIRST field, required, and a multi-select.
        self.assertEqual(list(form.fields)[0], 'campus')
        self.assertIsInstance(
            form.fields['campus'], dj_forms.ModelMultipleChoiceField)
        self.assertTrue(form.fields['campus'].required)
        qs = form.fields['campus'].queryset
        self.assertIn(self.campus_a, qs)
        self.assertNotIn(self.campus_b, qs)

    def test_ce_result_scoped_to_selected_own_campus(self):
        report = pending_future_classes_courses()
        qs = report.get_result(
            self._data(campus=[str(self.campus_a.id)]), user=self.ce)
        self.assertIn(self.cert_a, qs)
        self.assertNotIn(self.cert_b, qs)

    def test_ce_cannot_widen_to_inaccessible_campus(self):
        # selecting A (accessible) + B (not) keeps only A's certificates.
        report = pending_future_classes_courses()
        qs = report.get_result(
            self._data(campus=[str(self.campus_a.id), str(self.campus_b.id)]),
            user=self.ce)
        self.assertIn(self.cert_a, qs)
        self.assertNotIn(self.cert_b, qs)

    def test_ce_only_inaccessible_selection_returns_empty(self):
        report = pending_future_classes_courses()
        qs = report.get_result(
            self._data(campus=[str(self.campus_b.id)]), user=self.ce)
        self.assertNotIn(self.cert_a, qs)
        self.assertNotIn(self.cert_b, qs)

    def test_superuser_uses_selection_as_is(self):
        report = pending_future_classes_courses()
        qs = report.get_result(
            self._data(campus=[str(self.campus_b.id)]), user=self.superuser)
        self.assertIn(self.cert_b, qs)
        self.assertNotIn(self.cert_a, qs)
