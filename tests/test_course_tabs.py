from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import Course, CustomUser
from cis.models.course import Cohort


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class CourseTabDispatchTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.user = CustomUser.objects.create_superuser(
            username='tabtest', email='tabtest@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)
        cohort = Cohort.objects.create(name='Test Cohort', designator='TST')
        self.course = Course.objects.create(
            catalog_number='101',
            title='Tab Test',
            name='TAB101',
            cohort=cohort,
        )

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def test_unknown_tab_returns_404(self):
        url = reverse('cis:course_tab', args=[self.course.id, 'does_not_exist'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_offerings_tab_renders_sections_table(self):
        url = reverse('cis:course_tab', args=[self.course.id, 'class_sections'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # The sections_table partial boots its DataTable via initSectionsTable.
        self.assertIn('initSectionsTable', body)

    def test_change_history_tab_renders_history_table(self):
        url = reverse('cis:course_tab', args=[self.course.id, 'change_history'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('initChangeHistoryTable', body)
        self.assertIn('course_history', body)          # the table id
        self.assertNotIn('class="tab-pane"', body)     # bare inner partial, no wrapper

    def test_details_tab_renders_course_form(self):
        url = reverse('cis:course_tab', args=[self.course.id, 'details'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("name=\"action\" value='save_course'", body)
        self.assertIn('csrfmiddlewaretoken', body)     # the form's {% csrf_token %}

    def test_detail_page_renders_registry_tabs(self):
        resp = self.client.get(reverse('cis:course', args=[self.course.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # lazy panes are empty with a data-tab-url
        self.assertIn('id="class_sections" data-tab-url=', body)
        self.assertIn('id="change_history" data-tab-url=', body)
        # eager Details pane is pre-rendered (form present, no data-tab-url needed)
        self.assertIn("name=\"action\" value='save_course'", body)
        # nav still shows un-migrated tabs (regression)
        self.assertIn('href="#administrators"', body)
        # Regression: the lazy-tab loader must be present on the course detail page
        # (course.html extends logged-base-modal.html, which includes header-includes).
        self.assertIn('tab_loader.js', body)

    def test_instructors_tab_renders(self):
        resp = self.client.get(reverse('cis:course_tab', args=[self.course.id, 'instructors']))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('initInstructorsTable', resp.content.decode())

    def test_drop_wd_tab_renders(self):
        resp = self.client.get(reverse('cis:course_tab', args=[self.course.id, 'drop_wd']))
        self.assertEqual(resp.status_code, 200)

    def test_visits_tab_renders(self):
        resp = self.client.get(reverse('cis:course_tab', args=[self.course.id, 'visits']))
        self.assertEqual(resp.status_code, 200)

    def test_registrations_summary_tab_renders(self):
        resp = self.client.get(reverse('cis:course_tab', args=[self.course.id, 'registrations_summary']))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('tbl_registrations_summary', resp.content.decode())

    def test_notes_tab_renders(self):
        resp = self.client.get(reverse('cis:course_tab', args=[self.course.id, 'notes']))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('tbl_course_notes', resp.content.decode())

    def test_app_documents_tab_is_active_and_renders(self):
        resp = self.client.get(reverse('cis:course_tab', args=[self.course.id, 'app_documents']))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("name=\"action\" value='save_course_app_req'", resp.content.decode())

    def test_administrators_tab_renders(self):
        resp = self.client.get(reverse('cis:course_tab', args=[self.course.id, 'administrators']))
        self.assertEqual(resp.status_code, 200)

    def test_files_tab_renders(self):
        resp = self.client.get(reverse('cis:course_tab', args=[self.course.id, 'files']))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('name="action" value="upload_file"', resp.content.decode())

    def test_migrate_tab_renders(self):
        resp = self.client.get(reverse('cis:course_tab', args=[self.course.id, 'migrate']))
        self.assertEqual(resp.status_code, 200)

    def test_detail_page_renders_all_tabs_via_loop(self):
        resp = self.client.get(reverse('cis:course', args=[self.course.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for slug in ['details', 'instructors', 'class_sections', 'drop_wd',
                     'registrations_summary', 'app_documents', 'administrators',
                     'files', 'visits', 'notes', 'change_history', 'migrate']:
            self.assertIn('href="#%s"' % slug, body)
        self.assertIn('id="instructors" data-tab-url=', body)
        self.assertIn('id="app_documents"', body)
        self.assertIn("name=\"action\" value='save_course_app_req'", body)
        self.assertIn('tab_loader.js', body)
