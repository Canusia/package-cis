"""Phase 2: ClassSection + StudentRegistration campus scoping and gates."""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase, RequestFactory
from django.urls import reverse

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.term import AcademicYear, Term
from cis.models.course import Campus, Cohort, Course
from cis.models.section import ClassSection
from cis.views.section import ClassSectionViewSet

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class _NoLoginSignal(TestCase):
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


class SectionCampusScopeTests(_NoLoginSignal):
    def setUp(self):
        self.rf = RequestFactory()
        self.ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.term = Term.objects.create(
            academic_year=self.ay, code='FA', label=f'Fall-{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.course = Course.objects.create(
            catalog_number='101', title='Intro', cohort=self.cohort)
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.s_a = ClassSection.objects.create(
            class_number='1001', term=self.term, course=self.course, campus=self.campus_a)
        self.s_b = ClassSection.objects.create(
            class_number='1002', term=self.term, course=self.course, campus=self.campus_b)

        self.user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.user.campus = {'process_campus': [str(self.campus_a.id)]}
        self.user.save()
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.user)

    def _queryset(self):
        req = self.rf.get('/ce/api/class_section')
        req.user = self.user
        vs = ClassSectionViewSet()
        vs.request = req
        vs.format_kwarg = None
        return vs.get_queryset()

    def test_queryset_excludes_other_campus(self):
        qs = self._queryset()
        self.assertIn(self.s_a, qs)
        self.assertNotIn(self.s_b, qs)

    def test_detail_forbidden_for_other_campus(self):
        resp = self.client.get(reverse('cis:section', args=[self.s_b.id]))
        self.assertEqual(resp.status_code, 403)

    def test_index_renders_scoped_campus_dropdown(self):
        # /ce/sections must render a campus <select> populated only with the
        # caller's accessible campuses.
        resp = self.client.get(reverse('cis:sections'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('name="campus"', html)
        self.assertIn(self.campus_a.name, html)       # accessible
        self.assertNotIn(self.campus_b.name, html)     # not accessible


from cis.models.student import Student
from cis.models.section import StudentRegistration
from cis.views.registration import RegistrationViewSet


class RegistrationCampusScopeTests(_NoLoginSignal):
    def setUp(self):
        self.rf = RequestFactory()
        self.ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.term = Term.objects.create(
            academic_year=self.ay, code='FA', label=f'Fall-{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        # Campus is carried by the COURSE; a registration resolves campus via
        # class_section -> course -> campus. Sections deliberately have NO
        # campus of their own, proving the course path drives scoping.
        self.course_a = Course.objects.create(
            catalog_number='101', title='Intro-A', cohort=self.cohort, campus=self.campus_a)
        self.course_b = Course.objects.create(
            catalog_number='102', title='Intro-B', cohort=self.cohort, campus=self.campus_b)
        self.s_a = ClassSection.objects.create(
            class_number='1001', term=self.term, course=self.course_a)
        self.s_b = ClassSection.objects.create(
            class_number='1002', term=self.term, course=self.course_b)
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@x.com'})
        stu_user = User.objects.create_user(
            username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        self.stu = Student.objects.create(user=stu_user)
        _sco = {'applied_on': '01/01/2024'}
        self.r_a = StudentRegistration.objects.create(
            student=self.stu, class_section=self.s_a, status_changed_on=_sco)
        self.r_b = StudentRegistration.objects.create(
            student=self.stu, class_section=self.s_b, status_changed_on=_sco)

        self.user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.user.campus = {'process_campus': [str(self.campus_a.id)]}
        self.user.save()
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.user)

    def _queryset(self):
        req = self.rf.get(f'/ce/api/registration?term={self.term.id}')
        req.user = self.user
        vs = RegistrationViewSet()
        vs.request = req
        vs.format_kwarg = None
        return vs.get_queryset()

    def test_queryset_excludes_other_campus(self):
        qs = self._queryset()
        self.assertIn(self.r_a, qs)
        self.assertNotIn(self.r_b, qs)

    def test_detail_forbidden_for_other_campus(self):
        resp = self.client.get(reverse('cis:registration', args=[self.r_b.id]))
        self.assertEqual(resp.status_code, 403)

    def test_dropdown_filter_by_course_campus(self):
        # Selecting campus_b in the dropdown filters to registrations whose
        # section's course is on campus_b — but the ce user can't process
        # campus_b, so the security scope still excludes it (empty result).
        req = self.rf.get(
            f'/ce/api/registration?term={self.term.id}&campus={self.campus_b.id}')
        req.user = self.user
        vs = RegistrationViewSet()
        vs.request = req
        vs.format_kwarg = None
        qs = vs.get_queryset()
        self.assertNotIn(self.r_a, qs)
        self.assertNotIn(self.r_b, qs)

    def test_index_renders_scoped_campus_dropdown(self):
        resp = self.client.get(reverse('cis:registrations'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('name="campus"', html)
        self.assertIn(self.campus_a.name, html)       # accessible
        self.assertNotIn(self.campus_b.name, html)     # not accessible
