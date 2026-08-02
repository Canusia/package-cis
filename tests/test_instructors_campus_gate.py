"""Campus gate + dropdown for /ce/instructors (#all = Teacher, #by_highschool =
TeacherHighSchool). An instructor is scoped by the campuses of the courses they
are certified to teach; an instructor with NO course certificates is universal
(visible in every campus), like an unverified student. Superusers unscoped
(but may narrow via the dropdown)."""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from rest_framework.test import APIRequestFactory

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import Campus, Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate
from cis.views.teacher import TeacherViewSet
from cis.views.highschool import HighSchoolTeacherViewSet

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class InstructorsCampusGateTests(TestCase):
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
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.course_a = Course.objects.create(
            catalog_number='101', title='A', cohort=self.cohort, campus=self.campus_a)
        self.course_b = Course.objects.create(
            catalog_number='102', title='B', cohort=self.cohort, campus=self.campus_b)
        self.hs = HighSchool.objects.create(name=f'HS-{_sfx()}')

        self.teacher_a, self.th_a = self._teacher(self.course_a)
        self.teacher_b, self.th_b = self._teacher(self.course_b)
        self.teacher_none, self.th_none = self._teacher(None)  # no course certs

        self.ce = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.ce.campus = {'process_campus': [str(self.campus_a.id)]}
        self.ce.save()
        self.superuser = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')

    def _teacher(self, course):
        u = User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x')
        teacher = Teacher.objects.create(user=u)
        th = TeacherHighSchool.objects.create(teacher=teacher, highschool=self.hs)
        if course is not None:
            TeacherCourseCertificate.objects.create(
                teacher_highschool=th, course=course)
        return teacher, th

    def _teacher_qs(self, user, **params):
        req = APIRequestFactory().get('/x', params)
        req.user = user
        vs = TeacherViewSet()
        vs.request = req
        return vs.get_queryset()

    def _hs_qs(self, user, **params):
        req = APIRequestFactory().get('/x', params)
        req.user = user
        vs = HighSchoolTeacherViewSet()
        vs.request = req
        return vs.get_queryset()

    # --- #all (Teacher) ------------------------------------------------------
    def test_all_ce_scoped_by_cert_campus_and_keeps_no_cert(self):
        qs = self._teacher_qs(self.ce)
        self.assertIn(self.teacher_a, qs)       # certified at accessible campus A
        self.assertIn(self.teacher_none, qs)    # no course certs -> universal
        self.assertNotIn(self.teacher_b, qs)    # certified only at campus B

    def test_all_ce_with_both_campuses_sees_all(self):
        both = User.objects.create_user(
            username=f'ce2_{_sfx()}', email=f'ce2_{_sfx()}@x.com', password='x')
        both.groups.add(Group.objects.get_or_create(name='ce')[0])
        both.campus = {'process_campus': [str(self.campus_a.id),
                                          str(self.campus_b.id)]}
        both.save()
        qs = self._teacher_qs(both)
        self.assertIn(self.teacher_a, qs)
        self.assertIn(self.teacher_b, qs)
        self.assertIn(self.teacher_none, qs)

    def test_all_dropdown_narrows_but_keeps_no_cert(self):
        qs = self._teacher_qs(self.ce, campus=str(self.campus_a.id))
        self.assertIn(self.teacher_a, qs)
        self.assertIn(self.teacher_none, qs)
        self.assertNotIn(self.teacher_b, qs)

    # --- #by_highschool (TeacherHighSchool) ----------------------------------
    def test_by_hs_ce_scoped_by_cert_campus_and_keeps_no_cert(self):
        qs = self._hs_qs(self.ce)
        self.assertIn(self.th_a, qs)
        self.assertIn(self.th_none, qs)
        self.assertNotIn(self.th_b, qs)

    def test_by_hs_superuser_unscoped(self):
        self.assertIn(self.th_b, self._hs_qs(self.superuser))
