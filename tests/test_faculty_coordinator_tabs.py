"""Tab-registry tests for the FacultyCoordinator detail page.

EWU has no test factories; fixtures use direct Model.objects.create().
The django_login_history post_login receiver crashes on the test client's
request, so it is disconnected for the duration of each case (see
cis/tests/test_teacher_tabs.py).
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models.faculty import FacultyCoordinator

User = get_user_model()


def _disconnect_login_signal():
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


def _ce_user(email='ce-fc@example.com'):
    grp, _ = Group.objects.get_or_create(name='ce')
    user = User.objects.create_superuser(
        username=email, email=email, password='x')
    user.groups.add(grp)
    return user


def _make_coordinator(email='coord@example.com'):
    # FacultyCoordinator.save() does Group.objects.get(name='faculty')
    # (cis/models/faculty.py:48) and raises Group.DoesNotExist without it.
    Group.objects.get_or_create(name='faculty')
    coord_user = User.objects.create_user(
        username=email, email=email, password='x',
        first_name='Ada', last_name='Lovelace')
    return FacultyCoordinator.objects.create(user=coord_user)


class FacultyCoordinatorTabPlumbingTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        self.user = _ce_user()
        self.client.force_login(self.user)
        self.record = _make_coordinator()

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def _tab_url(self, slug):
        return reverse('cis:faculty_coordinator_tab',
                       kwargs={'record_id': self.record.pk, 'tab_slug': slug})

    def test_tab_url_reverses(self):
        self.assertIn(
            f'/ce/faculty_coordinator/{self.record.pk}/tab/courses/',
            self._tab_url('courses'))

    def test_unknown_slug_returns_404(self):
        resp = self.client.get(self._tab_url('definitely-not-a-tab'))
        self.assertEqual(resp.status_code, 404)


class FacultyCoordinatorLazyTabTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        self.user = _ce_user('ce-fc-lazy@example.com')
        self.client.force_login(self.user)
        self.record = _make_coordinator('coord-lazy@example.com')
        self.coord_user = self.record.user

        from cis.models.term import AcademicYear, Term
        from cis.models.course import Cohort, Course, CourseAdministrator
        self.ay = AcademicYear.objects.create(name='AY-lazy')
        self.term = Term.objects.create(
            academic_year=self.ay, code='FA', label='Fall-lazy')
        self.cohort = Cohort.objects.create(name='Co-lazy', designator='CL')
        self.course = Course.objects.create(
            catalog_number='101', title='Intro', cohort=self.cohort)
        CourseAdministrator.objects.create(
            course=self.course, user=self.coord_user, status='Active')

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def _fragment(self, slug):
        url = reverse('cis:faculty_coordinator_tab',
                      kwargs={'record_id': self.record.pk, 'tab_slug': slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    # --- registry contents ---
    def test_registry_exposes_expected_slugs_in_order(self):
        from myce.component_registry.faculty_coordinator import faculty_coordinator_tabs
        self.assertEqual(list(faculty_coordinator_tabs._tabs.keys()),
                         ['courses', 'class_sections', 'visits'])

    def test_courses_is_the_default_active_tab(self):
        from myce.component_registry.faculty_coordinator import faculty_coordinator_tabs
        self.assertTrue(faculty_coordinator_tabs._tabs['courses']['active'])

    def test_all_tabs_are_lazy(self):
        from myce.component_registry.faculty_coordinator import faculty_coordinator_tabs
        for slug, meta in faculty_coordinator_tabs._tabs.items():
            self.assertTrue(meta['lazy'], f'{slug} should be lazy')

    # --- courses ---
    def test_courses_fragment_has_table_and_own_init(self):
        html = self._fragment('courses')
        self.assertIn('id="table_course_administrator"', html)
        self.assertIn('DataTable(', html)
        self.assertIn('window.refreshTable', html)

    def test_courses_fragment_is_a_bare_partial(self):
        html = self._fragment('courses')
        self.assertNotIn('tab-pane', html)
        self.assertNotIn('<html', html)

    def test_courses_api_url_ampersand_is_not_html_escaped(self):
        html = self._fragment('courses')
        self.assertIn('&faculty_coordinator_user_id=', html)
        self.assertNotIn('&amp;faculty_coordinator_user_id=', html)

    # --- class_sections ---
    def test_class_sections_fragment_renders_sections_table(self):
        html = self._fragment('class_sections')
        self.assertIn('id="tbl_fc_class_sections"', html)
        self.assertIn('initSectionsTable', html)

    def test_class_sections_api_url_is_scoped_to_this_coordinator(self):
        html = self._fragment('class_sections')
        self.assertIn(
            f'course_administrator_user_id={self.coord_user.id}', html)

    def test_class_sections_has_term_filter_form_with_all_terms(self):
        html = self._fragment('class_sections')
        self.assertIn('id="fc_class_section_filter"', html)
        self.assertIn('name="term"', html)
        self.assertIn(str(self.term.id), html)

    # --- visits ---
    def test_visits_fragment_is_bare(self):
        html = self._fragment('visits')
        self.assertNotIn('tab-pane', html)


class FacultyCoordinatorDetailPageTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        self.user = _ce_user('ce-fc-detail@example.com')
        self.client.force_login(self.user)
        self.record = _make_coordinator('coord-detail@example.com')

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def _get(self):
        resp = self.client.get(reverse(
            'cis:faculty_coordinator', kwargs={'record_id': self.record.pk}))
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_all_tab_anchors_render(self):
        html = self._get().content.decode()
        for slug, title in [('courses', 'Course(s)'),
                            ('class_sections', 'Class Sections'),
                            ('visits', 'Visit(s)')]:
            self.assertIn(f'href="#{slug}"', html)
            self.assertIn(title, html)

    def test_active_lazy_pane_has_tab_url(self):
        html = self._get().content.decode()
        self.assertIn('data-tab-url', html)
        self.assertIn(
            f'/ce/faculty_coordinator/{self.record.pk}/tab/courses/', html)

    def test_tab_loader_js_is_loaded(self):
        self.assertContains(self._get(), 'tab_loader.js')

    def test_dropped_notes_tab_is_gone(self):
        html = self._get().content.decode()
        self.assertNotIn('href="#notes"', html)
        self.assertNotIn('data-model="teachernote"', html)

    def test_dead_records_active_init_is_gone(self):
        html = self._get().content.decode()
        self.assertNotIn('records_active', html)

    def test_table_markup_moved_out_of_the_page(self):
        # The courses table now lives in its fragment, not the detail page.
        html = self._get().content.decode()
        self.assertNotIn('id="table_course_administrator"', html)

    def test_edit_status_action_still_present(self):
        self.assertContains(self._get(), 'do_ajax_action')
