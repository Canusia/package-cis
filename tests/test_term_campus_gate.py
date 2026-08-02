"""Campus gate for /ce/terms: a term's campus is its academic year's campus.
A ce user sees only terms whose academic year is in a processable campus
(+ null-campus); the row exposes that campus. Superusers unscoped."""
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

from cis.models.term import AcademicYear, Term
from cis.models.course import Campus
from cis.serializers.term import TermSerializer
from cis.views.term import TermViewSet

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class TermCampusGateTests(TestCase):
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
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.ay_a = AcademicYear.objects.create(name=f'A-{_sfx()}', campus=self.campus_a)
        self.ay_b = AcademicYear.objects.create(name=f'B-{_sfx()}', campus=self.campus_b)
        self.ay_null = AcademicYear.objects.create(name=f'N-{_sfx()}', campus=None)
        self.term_a = Term.objects.create(academic_year=self.ay_a, code='FA', label='A')
        self.term_b = Term.objects.create(academic_year=self.ay_b, code='FB', label='B')
        self.term_null = Term.objects.create(
            academic_year=self.ay_null, code='FN', label='N')

        self.ce = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.ce.campus = {'process_campus': [str(self.campus_a.id)]}
        self.ce.save()
        self.superuser = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')

    def _qs(self, user):
        req = APIRequestFactory().get('/x')
        req.user = user
        vs = TermViewSet()
        vs.request = req
        return vs.get_queryset()

    def test_ce_sees_own_campus_and_null_not_other(self):
        qs = self._qs(self.ce)
        self.assertIn(self.term_a, qs)
        self.assertIn(self.term_null, qs)
        self.assertNotIn(self.term_b, qs)

    def test_superuser_unscoped(self):
        self.assertIn(self.term_b, self._qs(self.superuser))

    def test_serializer_exposes_campus_from_academic_year(self):
        self.assertEqual(
            TermSerializer(self.term_a).data['campus']['name'], self.campus_a.name)
        self.assertIsNone(TermSerializer(self.term_null).data['campus'])
