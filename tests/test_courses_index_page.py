from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models.customuser import CustomUser

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:
    _login_history_post_login = None


class CoursesIndexPageTests(TestCase):
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

    @classmethod
    def setUpTestData(cls):
        ce = Group.objects.get_or_create(name='ce')[0]
        cls.admin = CustomUser.objects.create(
            username='ce@x.com', email='ce@x.com', is_active=True)
        cls.admin.set_password('pw'); cls.admin.save()
        cls.admin.groups.add(ce)

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.admin)

    def test_index_renders_table_partials(self):
        resp = self.client.get(reverse('cis:courses'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # Tables courses.html owns are rendered via their table-config partials.
        self.assertIn('id="records_all"', html)
        self.assertIn('id="table_app_requirements"', html)
        self.assertIn('initCoursesTable', html)
        self.assertIn('initCourseAppRequirementsTable', html)
        # The kept instructor_app include still gets its context var.
        self.assertIn('course-app-requirement', html)
        # Old inline init must be gone.
        self.assertNotIn('table_app_requirements = $', html)
        # Template comments must not leak as literal page text (multi-line
        # {# #} is not a comment in Django — use {% comment %}).
        self.assertNotIn('duplicate-id collision', html)

    def test_course_administrators_tab_owned_solely_by_include(self):
        # The instructor_app include renders #course_administrators (and inits
        # table_course_administrator) itself. courses.html must NOT add a second
        # pane — a duplicate id collides and breaks DataTables reinit.
        resp = self.client.get(reverse('cis:courses'))
        html = resp.content.decode()
        self.assertEqual(html.count('id="course_administrators"'), 1)
        self.assertEqual(html.count('id="table_course_administrator"'), 1)
        # courses.html does not own this table, so its partial init is absent.
        self.assertNotIn('initCourseAdministratorsTable', html)

    def test_index_keeps_instructor_app_requirements_include(self):
        resp = self.client.get(reverse('cis:courses'))
        html = resp.content.decode()
        self.assertIn('id="course_requirements"', html)
