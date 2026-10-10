"""Shared fixtures for the term-hierarchy rollout tests (not a test module).

quarter -> (semester, trimester); spring is unrelated. One active section and
one registered student per leaf term, all on one prefixed campus.
"""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from rest_framework.test import APIRequestFactory

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import Campus, Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.term import AcademicYear, Term

User = get_user_model()


def sfx():
    return uuid.uuid4().hex[:8]


def make_registration(section, status='registered'):
    Group.objects.get_or_create(name='student')
    User.objects.get_or_create(username='cron', defaults={'email': 'cron@x.com'})
    user = User.objects.create_user(
        username=f'st_{sfx()}', email=f'st_{sfx()}@x.com', password='x')
    student = Student.objects.create(user=user, highschool=section.highschool)
    return StudentRegistration.objects.create(
        student=student, class_section=section, status=status,
        status_changed_on={})


def make_ce_user(*campuses):
    user = User.objects.create_user(
        username=f'ce_{sfx()}', email=f'ce_{sfx()}@x.com', password='x')
    user.groups.add(Group.objects.get_or_create(name='ce')[0])
    user.save()
    user.set_process_campuses([str(c.id) for c in campuses])
    return user


def run_viewset(viewset_cls, user, **params):
    request = APIRequestFactory().get('/x', params)
    request.user = user
    viewset = viewset_cls()
    viewset.request = request
    viewset.format_kwarg = None
    return viewset.get_queryset()


class TermTreeFixtureMixin:
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
        super().setUp()
        self.campus = Campus.objects.create(
            name=f'C-{sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{sfx()}')
        self.ay = AcademicYear.objects.create(name=f'AY-{sfx()}', campus=self.campus)

        def term(code, label, parent=None):
            return Term.objects.create(
                academic_year=self.ay, code=code, label=label, parent=parent)

        self.quarter = term('300', 'Fall Quarter')
        self.semester = term('290', 'Fall Semester', self.quarter)
        self.trimester = term('280', 'Fall Trimester', self.quarter)
        self.spring = term('200', 'Spring')

        self.course = Course.objects.create(
            catalog_number='101', title='Intro', campus=self.campus, credit_hours=3,
            cohort=Cohort.objects.create(name=f'Co-{sfx()}', designator='CO'))
        self.hs = HighSchool.objects.create(name=f'HS-{sfx()}')
        self.sections = {
            t.label: ClassSection.objects.create(
                class_number=f'CN{sfx()}', section_number='01', term=t,
                registration_term=t, course=self.course, highschool=self.hs,
                status='A')
            for t in (self.semester, self.trimester, self.spring)
        }
        self.registrations = {
            label: make_registration(section)
            for label, section in self.sections.items()
        }
        self.ce = make_ce_user(self.campus)

    def fall_labels(self):
        return {'Fall Semester', 'Fall Trimester'}
