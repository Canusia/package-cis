"""#41: the /ce/courses/ tabs come from course_index_tabs, so a tenant can drop one.

Also: `hidden=True` is honoured on the detail pages (it was documented and
ignored), and an index registry falls back to the first visible tab when the
default one is disabled.
"""
import copy
import re

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models.course import Cohort, Course
from cis.models.customuser import CustomUser
from cis.tabs.course_index import course_index_tabs

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None


def _nav(html):
    """[(slug, classes on the <li>, is-active)] for the courses index nav."""
    return [
        (slug, li_class, 'active' in a_class)
        for li_class, a_class, slug in re.findall(
            r'<li class="(nav-item[^"]*)">\s*<a class="(nav-link[^"]*)" '
            r'data-toggle="tab" href="#([a-z_]+)"', html)
    ]


class _LoggedInCE(TestCase):
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
        admin = CustomUser.objects.create_superuser(
            username='su@x.com', email='su@x.com', password='x')
        admin.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(admin)


class CoursesIndexTabsTests(_LoggedInCE):
    def setUp(self):
        super().setUp()
        saved = copy.deepcopy(course_index_tabs._tabs)
        self.addCleanup(setattr, course_index_tabs, '_tabs', saved)

    def _page(self):
        resp = self.client.get(reverse('cis:courses'))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_default_nav_matches_the_old_markup(self):
        nav = _nav(self._page())
        self.assertEqual([slug for slug, _, _ in nav], [
            'all', 'course_requirements', 'course_administrators',
            'app_requirements', 'document_requirements'])
        classes = {slug: li for slug, li, _ in nav}
        self.assertIn('d-none', classes['course_requirements'])
        self.assertNotIn('d-none', classes['app_requirements'])
        self.assertEqual([slug for slug, _, active in nav if active], ['all'])

    def test_disabled_tabs_drop_nav_pane_and_table_init(self):
        course_index_tabs.disable('course_administrators', 'app_requirements')
        html = self._page()

        slugs = [slug for slug, _, _ in _nav(html)]
        self.assertNotIn('course_administrators', slugs)
        self.assertNotIn('app_requirements', slugs)
        # Panes and their DataTables are gone, so no API calls fire for them.
        self.assertNotIn('id="course_administrators"', html)
        self.assertNotIn("$('#table_course_administrator')", html)
        self.assertNotIn('id="app_requirements"', html)
        self.assertNotIn('initCourseAppRequirementsTable', html)
        # The rest are untouched.
        self.assertIn('id="course_requirements"', html)
        self.assertIn("$('#table_course_requirements')", html)
        self.assertIn('id="document_requirements"', html)

    def test_disabling_the_default_falls_back_to_the_first_visible_tab(self):
        course_index_tabs.disable('all')
        nav = _nav(self._page())
        # course_requirements is hidden, so the next visible tab takes over.
        self.assertEqual(
            [slug for slug, _, active in nav if active], ['course_administrators'])

    def test_set_active(self):
        course_index_tabs.set_active('document_requirements')
        html = self._page()
        self.assertEqual(
            [slug for slug, _, active in _nav(html) if active],
            ['document_requirements'])
        self.assertIn('class="tab-pane active" id="document_requirements"', html)

    def test_unknown_slug_raises(self):
        with self.assertRaises(KeyError):
            course_index_tabs.disable('no_such_tab')
        with self.assertRaises(KeyError):
            course_index_tabs.set_active('no_such_tab')


class DetailTabHiddenTests(_LoggedInCE):
    def test_hidden_tab_nav_carries_d_none_on_course_detail(self):
        from myce.component_registry.course import course_tabs
        slug = next(iter(course_tabs._tabs))
        saved = course_tabs._tabs[slug]['hidden']
        course_tabs._tabs[slug]['hidden'] = True
        self.addCleanup(course_tabs._tabs[slug].__setitem__, 'hidden', saved)

        course = Course.objects.create(
            catalog_number='101', title='A',
            cohort=Cohort.objects.create(name='C', designator='C'))
        resp = self.client.get(reverse('cis:course', args=[course.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertRegex(
            resp.content.decode(),
            rf'<li class="nav-item d-none">\s*<a class="nav-link[^"]*"[^>]*href="#{slug}"')
