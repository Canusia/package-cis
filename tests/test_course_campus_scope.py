"""CourseViewSet is campus-scoped for ce staff (/ce/api/course)."""
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

from cis.models.course import Campus, Cohort, Course
from cis.views.course import CourseViewSet

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class CourseViewSetCampusScopeTests(TestCase):
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
        self.rf = RequestFactory()
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.c_a = Course.objects.create(
            catalog_number='101', title='A', cohort=self.cohort, campus=self.campus_a)
        self.c_b = Course.objects.create(
            catalog_number='201', title='B', cohort=self.cohort, campus=self.campus_b)
        self.c_none = Course.objects.create(
            catalog_number='100', title='N', cohort=self.cohort, campus=None)

        self.user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.user.campus = {'process_campus': [str(self.campus_a.id)]}
        self.user.save()

    def _queryset(self):
        req = self.rf.get('/ce/api/course')
        req.user = self.user
        vs = CourseViewSet()
        vs.request = req
        vs.format_kwarg = None
        return vs.get_queryset()

    def test_own_and_null_included_other_excluded(self):
        qs = self._queryset()
        self.assertIn(self.c_a, qs)
        self.assertIn(self.c_none, qs)
        self.assertNotIn(self.c_b, qs)


from django.urls import reverse


class CourseDetailDeleteGateTests(TestCase):
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
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.c_a = Course.objects.create(
            catalog_number='101', title='A', cohort=self.cohort, campus=self.campus_a)
        self.c_b = Course.objects.create(
            catalog_number='201', title='B', cohort=self.cohort, campus=self.campus_b)

        self.user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.user.campus = {'process_campus': [str(self.campus_a.id)]}
        self.user.save()
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.user)

    def test_detail_allowed_for_own_campus(self):
        resp = self.client.get(reverse('cis:course', args=[self.c_a.id]))
        self.assertEqual(resp.status_code, 200)

    def test_detail_forbidden_for_other_campus(self):
        resp = self.client.get(reverse('cis:course', args=[self.c_b.id]))
        self.assertEqual(resp.status_code, 403)

    def test_delete_forbidden_for_other_campus(self):
        resp = self.client.get(reverse('cis:delete_course', args=[self.c_b.id]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Course.objects.filter(pk=self.c_b.id).exists())


class CoursesDropdownTests(TestCase):
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
            name=f'Alpha-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'Beta-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.user.campus = {
            'process_campus': [str(self.campus_a.id)],
            'default_campus': str(self.campus_a.id),
        }
        self.user.save()
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.user)

    def test_dropdown_shows_only_accessible_campus_default_selected(self):
        resp = self.client.get(reverse('cis:courses'))
        html = resp.content.decode()
        self.assertIn('id="courses_campus_filter"', html)
        self.assertIn(self.campus_a.name, html)          # accessible
        self.assertNotIn(self.campus_b.name, html)       # not accessible
        # default campus option is pre-selected
        self.assertIn(f'value="{self.campus_a.id}" selected', html)


class CoursesCampusSentinelTests(TestCase):
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
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.c_a = Course.objects.create(
            catalog_number='101', title='A', cohort=self.cohort, campus=self.campus_a)
        self.c_b = Course.objects.create(
            catalog_number='201', title='B', cohort=self.cohort, campus=self.campus_b)
        # ce user with an accessible campus but NO default_campus set
        self.user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.user.campus = {'process_campus': [str(self.campus_a.id)]}
        self.user.save()
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.user)

    def test_all_my_campuses_sentinel_does_not_500(self):
        # "All My Campuses" => campus=-1; must 200, and still be campus-scoped.
        resp = self.client.get('/ce/api/course/?format=datatables&campus=-1')
        self.assertEqual(resp.status_code, 200, resp.content)
        ids = [row['id'] for row in resp.json()['data']]
        self.assertIn(str(self.c_a.id), ids)       # accessible campus present
        self.assertNotIn(str(self.c_b.id), ids)    # security scope still excludes other campus

    def test_courses_page_loads_without_default_campus(self):
        resp = self.client.get(reverse('cis:courses'))
        self.assertEqual(resp.status_code, 200)


class CourseBulkActionCampusGateTests(TestCase):
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
        self.dest = Campus.objects.create(
            name=f'D-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.c_a = Course.objects.create(
            catalog_number='101', title='A', cohort=self.cohort, campus=self.campus_a)
        self.c_b = Course.objects.create(
            catalog_number='201', title='B', cohort=self.cohort, campus=self.campus_b)
        self.user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.user.campus = {'process_campus': [str(self.campus_a.id)]}
        self.user.save()
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.user)

    def test_bulk_campus_update_skips_out_of_scope_course(self):
        # ce user can process campus_a only. Try to move BOTH c_a and c_b to dest.
        resp = self.client.post(reverse('cis:course_bulk_actions'), {
            'action': 'update_course_campus',
            'action_confirmed': '1',
            'ids[]': [str(self.c_a.id), str(self.c_b.id)],
            'campus': str(self.dest.id),
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        self.c_a.refresh_from_db(); self.c_b.refresh_from_db()
        self.assertEqual(self.c_a.campus_id, self.dest.id)   # in-scope: moved
        self.assertEqual(self.c_b.campus_id, self.campus_b.id)  # out-of-scope: untouched
