"""Plumbing and dispatch tests for student tab registry wiring."""
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.student import Student
from cis.models.term import AcademicYear, Term
from myce.component_registry.student import student_tabs


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class StudentTabsPlumbingTest(TestCase):
    def test_unknown_slug_returns_404(self):
        from django.test import RequestFactory
        from django.contrib.auth.models import AnonymousUser
        rf = RequestFactory()
        request = rf.get('/')
        request.user = AnonymousUser()

        class _FakeStudent:
            id = 'fake-id'

        resp = student_tabs.render_tab(request, _FakeStudent(), 'does_not_exist')
        self.assertEqual(resp.status_code, 404)

    def test_registry_imported_without_error(self):
        # Confirms the eager import of cis.tabs.student ran successfully
        self.assertIsNotNone(student_tabs)


class StudentTabDispatchTest(TestCase):
    """Dispatch tests for all LAZY tabs — requires a real Student in the DB."""

    def setUp(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        # Student.save() calls Group.objects.get(name='student') unconditionally
        Group.objects.get_or_create(name='student')
        # The onboarding context processor calls active_term() which returns
        # Term.objects.first(). With no Term, get_or_create_for_current_term
        # tries to create StudentOnboarding(term=None) → IntegrityError.
        ay = AcademicYear.objects.create(name='Test Year')
        self.term = Term.objects.create(academic_year=ay, code='TST', label='Test Term')
        self.user = CustomUser.objects.create_superuser(
            username='studtab', email='studtab@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)
        self.student = Student.objects.create(user=self.user)

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def _tab_url(self, slug):
        return reverse('cis:student_tab', args=[self.student.id, slug])

    def test_details_tab_200(self):
        resp = self.client.get(self._tab_url('details'))
        self.assertEqual(resp.status_code, 200)

    def test_ferpa_tab_200(self):
        resp = self.client.get(self._tab_url('ferpa'))
        self.assertEqual(resp.status_code, 200)

    def test_recommendations_tab_200(self):
        resp = self.client.get(self._tab_url('recommendations'))
        self.assertEqual(resp.status_code, 200)

    def test_agreements_tab_200(self):
        resp = self.client.get(self._tab_url('agreements'))
        self.assertEqual(resp.status_code, 200)

    def test_drop_wd_tab_200(self):
        resp = self.client.get(self._tab_url('drop_wd'))
        self.assertEqual(resp.status_code, 200)

    def test_parent_consents_tab_200(self):
        resp = self.client.get(self._tab_url('parent_consents'))
        self.assertEqual(resp.status_code, 200)

    def test_transactions_tab_200(self):
        resp = self.client.get(self._tab_url('transactions'))
        self.assertEqual(resp.status_code, 200)

    def test_notes_tab_200(self):
        resp = self.client.get(self._tab_url('notes'))
        self.assertEqual(resp.status_code, 200)

    def test_change_history_tab_200(self):
        resp = self.client.get(self._tab_url('change_history'))
        self.assertEqual(resp.status_code, 200)

    def test_unknown_tab_returns_404(self):
        resp = self.client.get(self._tab_url('does_not_exist'))
        self.assertEqual(resp.status_code, 404)

    def test_student_filter_urls_are_not_html_escaped(self):
        """Regression: agreements/parent_consents/transactions render their api
        URL inside a <script> string; the `&` must stay literal (mark_safe) so
        the ?student= filter is sent. If it escapes to &amp;student=, the
        viewset sees no student and returns every student's records."""
        sid = str(self.student.id)
        cases = [
            ('agreements', '&student=%s' % sid),
            ('parent_consents', '&student=%s' % sid),
            ('transactions', '&student_id=%s' % sid),
        ]
        for slug, expected in cases:
            body = self.client.get(self._tab_url(slug)).content.decode()
            self.assertIn(expected, body, slug)
            self.assertNotIn('&amp;student', body, slug)


class StudentEagerTabTest(TestCase):
    """Dispatch tests for EAGER form tabs — require a real Student in the DB."""

    def setUp(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        Group.objects.get_or_create(name='student')
        ay = AcademicYear.objects.create(name='Test Year Eager')
        self.term = Term.objects.create(academic_year=ay, code='EGR', label='Eager Term')
        self.user = CustomUser.objects.create_superuser(
            username='eagertab', email='eagertab@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)
        self.student = Student.objects.create(user=self.user)

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def _tab_url(self, slug):
        return reverse('cis:student_tab', args=[self.student.id, slug])

    def test_classes_tab_200(self):
        resp = self.client.get(self._tab_url('classes'))
        self.assertEqual(resp.status_code, 200)

    def test_files_tab_200(self):
        resp = self.client.get(self._tab_url('files'))
        self.assertEqual(resp.status_code, 200)

    def test_campus_id_tab_200(self):
        resp = self.client.get(self._tab_url('campus_id'))
        self.assertEqual(resp.status_code, 200)

    def test_migrate_tab_200(self):
        resp = self.client.get(self._tab_url('migrate'))
        self.assertEqual(resp.status_code, 200)


class StudentDetailRenderTest(TestCase):
    """Task 4d — verify the collapsed detail template renders correctly via the
    registry loop (all 13 tabs present, state_q absent, lazy/eager panes wired,
    tab_loader.js present)."""

    EXPECTED_TAB_HREFS = [
        b'href="#details"',
        b'href="#ferpa"',
        b'href="#recommendations"',
        b'href="#agreements"',
        b'href="#classes"',
        b'href="#files"',
        b'href="#drop_wd"',
        b'href="#campus_id"',
        b'href="#parent_consents"',
        b'href="#transactions"',
        b'href="#notes"',
        b'href="#change_history"',
        b'href="#migrate"',
    ]

    def setUp(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        Group.objects.get_or_create(name='student')
        ay = AcademicYear.objects.create(name='Render Test Year')
        Term.objects.create(academic_year=ay, code='RND', label='Render Term')
        self.user = CustomUser.objects.create_superuser(
            username='rendertest', email='rendertest@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)
        self.student = Student.objects.create(user=self.user)

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def _detail_url(self):
        return reverse('cis:student', args=[self.student.id])

    def test_detail_page_renders_200(self):
        resp = self.client.get(self._detail_url())
        self.assertEqual(resp.status_code, 200)

    def test_all_13_tab_hrefs_present(self):
        resp = self.client.get(self._detail_url())
        content = resp.content
        for href in self.EXPECTED_TAB_HREFS:
            self.assertIn(href, content, msg=f'{href.decode()} not found in response')

    def test_state_q_tab_absent(self):
        resp = self.client.get(self._detail_url())
        self.assertNotIn(b'href="#state_q"', resp.content)
        self.assertNotIn(b'id="state_q"', resp.content)

    def test_active_tab_is_classes(self):
        resp = self.client.get(self._detail_url())
        self.assertIn(b'id="classes"', resp.content)
        # The classes tab is eager (not lazy) — its html is pre-rendered inline
        self.assertNotIn(b'data-tab-url="/ce/student/' + str(self.student.id).encode() + b'/tab/classes/"',
                         resp.content)

    def test_lazy_panes_have_data_tab_url(self):
        resp = self.client.get(self._detail_url())
        self.assertIn(b'data-tab-url=', resp.content)

    def test_tab_loader_js_present(self):
        resp = self.client.get(self._detail_url())
        self.assertIn(b'tab_loader.js', resp.content)
