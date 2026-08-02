"""Campus gate + dropdown for /ce/faculty. The table lists CourseAdministrator
(course<->faculty) rows, scoped by the administered course's campus; the campus
dropdown narrows within the ce user's processable campuses."""
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

from cis.models.course import Campus, Cohort, Course, CourseAdministrator
from cis.views.faculty import CourseAdministratorViewSet

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class FacultyCampusGateTests(TestCase):
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
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.course_a = Course.objects.create(
            catalog_number='101', title='A', cohort=self.cohort, campus=self.campus_a)
        self.course_b = Course.objects.create(
            catalog_number='102', title='B', cohort=self.cohort, campus=self.campus_b)
        fac = User.objects.create_user(
            username=f'fac_{_sfx()}', email=f'fac_{_sfx()}@x.com', password='x')
        self.ca_a = CourseAdministrator.objects.create(course=self.course_a, user=fac)
        self.ca_b = CourseAdministrator.objects.create(course=self.course_b, user=fac)

        self.ce = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.ce.campus = {'process_campus': [str(self.campus_a.id)]}
        self.ce.save()
        self.superuser = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')

    def _qs(self, user, **params):
        req = APIRequestFactory().get('/x', params)
        req.user = user
        vs = CourseAdministratorViewSet()
        vs.request = req
        return vs.get_queryset()

    def test_ce_scoped_to_own_campus(self):
        qs = self._qs(self.ce)
        self.assertIn(self.ca_a, qs)
        self.assertNotIn(self.ca_b, qs)

    def test_superuser_unscoped(self):
        self.assertIn(self.ca_b, self._qs(self.superuser))

    def test_ce_dropdown_narrows_to_own_campus(self):
        qs = self._qs(self.ce, campus=str(self.campus_a.id))
        self.assertIn(self.ca_a, qs)
        self.assertNotIn(self.ca_b, qs)

    def test_ce_cannot_widen_to_inaccessible_campus(self):
        # campus B isn't in the ce user's dropdown, but even if forced it can't
        # surface B's rows (the gate strips them before the campus filter).
        qs = self._qs(self.ce, campus=str(self.campus_b.id))
        self.assertNotIn(self.ca_b, qs)

    def test_superuser_dropdown_narrows(self):
        qs = self._qs(self.superuser, campus=str(self.campus_a.id))
        self.assertIn(self.ca_a, qs)
        self.assertNotIn(self.ca_b, qs)
