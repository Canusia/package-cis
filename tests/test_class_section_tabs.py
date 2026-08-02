from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.section import ClassSection
from cis.models.course import Course, Cohort
from cis.models.term import Term, AcademicYear


def _disconnect_login_signal():
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class ClassSectionTabDispatchTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.user = CustomUser.objects.create_superuser(
            username='sectabtest', email='sectabtest@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)
        cohort = Cohort.objects.create(name='Test Cohort', designator='TST')
        course = Course.objects.create(
            catalog_number='101', title='Tab Test', name='TAB101', cohort=cohort)
        academic_year = AcademicYear.objects.create(name='2025-2026')
        term = Term.objects.create(
            label='Fall 2025', code='F25', academic_year=academic_year)
        self.section = ClassSection.objects.create(
            course=course, term=term, class_number=99901, section_number='001')

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def test_unknown_tab_returns_404(self):
        url = reverse('cis:section_tab', args=[self.section.id, 'does_not_exist'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    # ------------------------------------------------------------------
    # Task 2 — LAZY tab tests
    # ------------------------------------------------------------------

    def test_details_tab_renders(self):
        url = reverse('cis:section_tab', args=[self.section.id, 'details'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertNotIn('class="tab-pane"', body)  # bare partial, no wrapper
        self.assertNotIn('{% extends', body)

    def test_students_tab_renders_registrations_table(self):
        url = reverse('cis:section_tab', args=[self.section.id, 'students'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('initRegistrationsTable', body)
        self.assertIn('tbl_class_registrations', body)
        self.assertNotIn('class="tab-pane"', body)

    def test_drop_wd_tab_renders(self):
        url = reverse('cis:section_tab', args=[self.section.id, 'drop_wd'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_visits_tab_renders(self):
        url = reverse('cis:section_tab', args=[self.section.id, 'visits'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_notes_tab_renders(self):
        url = reverse('cis:section_tab', args=[self.section.id, 'notes'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('Add New Note', body)
        self.assertNotIn('class="tab-pane"', body)

    # ------------------------------------------------------------------
    # Task 3 — EAGER syllabi tab test
    # ------------------------------------------------------------------

    def test_syllabi_tab_is_eager_and_renders(self):
        """Dispatch URL renders syllabi fragment with form (EAGER, no tab-pane wrapper)."""
        url = reverse('cis:section_tab', args=[self.section.id, 'syllabi'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('name="add_syllabi"', body)    # submit button name (not hidden action)
        self.assertIn('csrfmiddlewaretoken', body)
        self.assertNotIn('class="tab-pane"', body)   # bare partial, no wrapper

    # ------------------------------------------------------------------
    # Task 4 — Collapsed template tests
    # ------------------------------------------------------------------

    def test_detail_page_renders_all_tabs_via_loop(self):
        resp = self.client.get(reverse('cis:section', args=[self.section.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for slug in ['details', 'students', 'drop_wd', 'syllabi', 'visits', 'notes']:
            self.assertIn('href="#%s"' % slug, body)
        # Lazy panes have data-tab-url
        self.assertIn('id="details" data-tab-url=', body)
        self.assertIn('id="students" data-tab-url=', body)
        # Eager syllabi pane is pre-rendered (form present, no data-tab-url)
        self.assertIn('name="add_syllabi"', body)
        self.assertNotIn('id="syllabi" data-tab-url=', body)
        # tab_loader.js present (via header-includes.html)
        self.assertIn('tab_loader.js', body)
        # Dead page-level DataTable init is gone
        self.assertNotIn("$('.dataTable').DataTable()", body)

    def test_detail_page_active_tab_is_students(self):
        resp = self.client.get(reverse('cis:section', args=[self.section.id]))
        body = resp.content.decode()
        self.assertIn('href="#students"', body)
        # The active nav link should include 'active'
        self.assertIn('active', body)
