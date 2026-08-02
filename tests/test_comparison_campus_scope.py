"""The academic-years compare panel scopes the selectable records to the ce
user's processable campuses (+ null-campus) and tags each with its campus_id so
the panel can cascade off a campus selector."""
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

from cis.models.term import AcademicYear
from cis.models.course import Campus
from cis.services.comparison import build_compare_context

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class CompareCampusScopeTests(TestCase):
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

    def _ctx(self, user):
        req = RequestFactory().get('/')
        req.user = user
        return build_compare_context(req, 'academic_year')

    def test_records_scoped_to_campus_with_campus_id(self):
        recs = self._ctx(self.ce)['compare_records']
        ids = {r['id'] for r in recs}
        self.assertIn(str(self.ay_a.id), ids)      # own campus
        self.assertIn(str(self.ay_null.id), ids)   # null-campus -> universal
        self.assertNotIn(str(self.ay_b.id), ids)   # other campus
        by_id = {r['id']: r for r in recs}
        self.assertEqual(by_id[str(self.ay_a.id)]['campus_id'], str(self.campus_a.id))
        self.assertEqual(by_id[str(self.ay_null.id)]['campus_id'], '')
