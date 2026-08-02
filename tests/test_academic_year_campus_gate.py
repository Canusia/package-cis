"""Campus gate for /ce/academic_years/: a ce user sees only academic years for
their processable campuses (+ null-campus); the row exposes its campus; the
form lets you set it. Superusers/non-ce unscoped."""
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

from cis.models.term import AcademicYear
from cis.models.course import Campus
from cis.serializers.term import AcademicYearListSerializer
from cis.forms.term import AcademicYearForm
from cis.views.academic_year import AcademicYearViewSet

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class AcademicYearCampusGateTests(TestCase):
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
        vs = AcademicYearViewSet()
        vs.request = req
        return vs.get_queryset()

    def test_ce_sees_own_campus_and_null_not_other(self):
        qs = self._qs(self.ce)
        self.assertIn(self.ay_a, qs)
        self.assertIn(self.ay_null, qs)
        self.assertNotIn(self.ay_b, qs)

    def test_superuser_unscoped(self):
        qs = self._qs(self.superuser)
        self.assertIn(self.ay_b, qs)

    def test_serializer_exposes_campus(self):
        data = AcademicYearListSerializer(self.ay_a).data
        self.assertEqual(data['campus']['name'], self.campus_a.name)
        self.assertIsNone(AcademicYearListSerializer(self.ay_null).data['campus'])

    def test_form_has_editable_campus_field(self):
        form = AcademicYearForm()
        self.assertIn('campus', form.fields)
