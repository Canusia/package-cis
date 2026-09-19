"""The Failed SIS Mirror tab's filter bar.

The page reuses the Registrations tab's controls (term / registration status /
record type / student agreement / campus) and the same query-param names, so
both feeds read a filter identically. The one intentional divergence is the
term default: Registrations falls back to the active term when `term` is
absent, which on a triage page would silently hide older failures, so here an
absent or blank term means every term.

Both the DataTables feed and the "Export All" CSV run through the same
apply_filters(), so the export can never disagree with what is on screen.
"""
import csv
import io
import json

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.course import Campus, Cohort, Course
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.term import AcademicYear, Term


def _disconnect_login_signal():
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class FailedMirrorFilterTests(TestCase):
    """One failed registration per term/campus/status, then filter for each."""

    def setUp(self):
        self._saved = _disconnect_login_signal()

        Group.objects.get_or_create(name='student')
        ce_group, _ = Group.objects.get_or_create(name='ce')

        if not CustomUser.objects.filter(username='cron').exists():
            CustomUser.objects.create_user(
                username='cron', email='cron@example.com', password='x')

        ay = AcademicYear.objects.create(name='2025-2026-FMF')
        self.fall = Term.objects.create(
            label='Fall 2025 FMF', code='F25FMF', academic_year=ay)
        self.spring = Term.objects.create(
            label='Spring 2026 FMF', code='S26FMF', academic_year=ay)

        self.campus_a = Campus.objects.create(name='FMF Campus A', code='FMFA')
        self.campus_b = Campus.objects.create(name='FMF Campus B', code='FMFB')

        cohort = Cohort.objects.create(name='FMF Cohort', designator='FMFC')
        course_a = Course.objects.create(
            catalog_number='301', title='FMF A', name='FMF301',
            cohort=cohort, campus=self.campus_a, prereq='ENG 101')
        course_b = Course.objects.create(
            catalog_number='302', title='FMF B', name='FMF302',
            cohort=cohort, campus=self.campus_b, prereq='')

        self.fall_section = ClassSection.objects.create(
            course=course_a, term=self.fall,
            class_number=88811, section_number='001')
        self.spring_section = ClassSection.objects.create(
            course=course_b, term=self.spring,
            class_number=88812, section_number='001')

        # Fall / campus A / approved / not needing mirroring / has a prereq.
        self.fall_reg = self._registration(
            'fmffall', self.fall_section, status='approved',
            needs_mirroring=False)
        # Spring / campus B / applied / needs mirroring / no prereq.
        self.spring_reg = self._registration(
            'fmfspring', self.spring_section, status='applied',
            needs_mirroring=True)

        # A registration that mirrored fine — never in this table, filtered or not.
        self._registration(
            'fmfok', self.fall_section, status='approved',
            needs_mirroring=False, last_mirror_status='success')

        self.user = CustomUser.objects.create_superuser(
            username='fmftest', email='fmftest@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)

        self.api_url = reverse('cis:failed_mirror_registrations-list')
        self.export_url = reverse('cis:registrations_failed_mirror_export')

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def _registration(self, username, section, status, needs_mirroring,
                      last_mirror_status='failed'):
        user = CustomUser.objects.create_user(
            username=username, email=f'{username}@example.com', password='x',
            first_name=username, last_name='Student')
        student = Student.objects.create(user=user)
        return StudentRegistration.objects.create(
            student=student, class_section=section,
            status=status, status_changed_on={},
            needs_mirroring=needs_mirroring,
            last_mirror_status=last_mirror_status,
        )

    def _feed_ids(self, **params):
        """Row ids the DataTables feed returns for the given filter params."""
        query = {'format': 'datatables', 'draw': '1',
                 'start': '0', 'length': '30'}
        query.update(params)
        resp = self.client.get(self.api_url, query)
        self.assertEqual(resp.status_code, 200, resp.content[:400])
        payload = json.loads(resp.content)
        return {row['id'] for row in payload['data']}

    def _export_names(self, **params):
        resp = self.client.get(self.export_url, params)
        self.assertEqual(resp.status_code, 200)
        rows = list(csv.reader(io.StringIO(resp.content.decode())))
        return {row[0] for row in rows[1:]}

    # --- the controls the page renders -------------------------------------

    def test_page_renders_the_registrations_tab_controls(self):
        resp = self.client.get(reverse('cis:registrations_failed_mirror'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content
        for name in (b'name="term"', b'name="status"', b'name="record_type"',
                     b'name="signed_student_agreement"',
                     b'name="signed_parent_consent"', b'name="campus"'):
            self.assertIn(name, content)
        self.assertIn(b'id_btn_filter', content)
        # The table feed must be seeded from the form, not the bare data_url.
        self.assertIn(b'filteredUrl()', content)

    def test_page_defaults_the_term_dropdown_to_every_term(self):
        resp = self.client.get(reverse('cis:registrations_failed_mirror'))
        self.assertIn(b'<option selected value="-3">By Term</option>',
                      resp.content)

    def test_page_offers_no_record_type_the_feed_cannot_apply(self):
        """Every option in the bar must do something.

        The Registrations tab's "**SIS Error(s)" has no branch in
        apply_filters, so it read as applied and returned every row. It is
        dropped here rather than implemented -- every row on this page is
        already a failed SIS mirror.
        """
        resp = self.client.get(reverse('cis:registrations_failed_mirror'))
        record_type = resp.content.decode().split(
            'name="record_type"', 1)[1].split('</select>', 1)[0]
        self.assertNotIn('sis_error', record_type)
        for implemented in ('with_prereq', 'needs_mirroring'):
            self.assertIn(implemented, record_type)

    def test_page_does_not_preselect_a_campus(self):
        """Same rule as the term default, for the same reason.

        get_default_campus() returns the user's saved campus, or the first
        campus when they have none. Handing that to snippets/campus.html
        pre-selects it, and the table's first request is built from the form --
        so the page opened already narrowed to one campus, and Export All
        inherited the hidden filter.
        """
        # The dropdown lists only campuses carrying the tenant code prefix, and
        # a saved default is the strongest form of the bug -- get_default_campus
        # returns it outright rather than falling back to the first campus.
        listed = Campus.objects.create(
            name='FMF Listed', code=f'{settings.CAMPUS_CODE_PREFIX}FMF1')
        self.user.campus = {'default_campus': str(listed.id),
                            'process_campus': [str(listed.id)]}
        self.user.save()

        resp = self.client.get(reverse('cis:registrations_failed_mirror'))
        campus_select = resp.content.decode().split(
            'name="campus"', 1)[1].split('</select>', 1)[0]
        self.assertIn(str(listed.id), campus_select)
        self.assertNotIn('selected', campus_select)

    # --- filtering ----------------------------------------------------------

    def test_no_filter_returns_every_failed_registration(self):
        ids = self._feed_ids()
        self.assertEqual(ids, {str(self.fall_reg.id), str(self.spring_reg.id)})

    def test_blank_term_does_not_fall_back_to_the_active_term(self):
        """Registrations defaults an absent term; this triage page must not."""
        for term in ('', '-1', '-3'):
            self.assertEqual(
                self._feed_ids(term=term),
                {str(self.fall_reg.id), str(self.spring_reg.id)},
                f'term={term!r} should mean every term')

    def test_term_filter(self):
        self.assertEqual(self._feed_ids(term=str(self.fall.id)),
                         {str(self.fall_reg.id)})
        self.assertEqual(self._feed_ids(term=str(self.spring.id)),
                         {str(self.spring_reg.id)})

    def test_malformed_term_returns_no_rows_instead_of_500(self):
        self.assertEqual(self._feed_ids(term='not-a-uuid'), set())

    def test_status_filter(self):
        self.assertEqual(self._feed_ids(status='applied'),
                         {str(self.spring_reg.id)})
        self.assertEqual(self._feed_ids(status='approved'),
                         {str(self.fall_reg.id)})

    def test_record_type_needs_mirroring(self):
        self.assertEqual(self._feed_ids(record_type='needs_mirroring'),
                         {str(self.spring_reg.id)})

    def test_record_type_with_prereq_selects_courses_that_have_prereqs(self):
        """'With Prereqs' means the course has one -- fall_reg, not spring_reg.

        This deliberately diverges from the Registrations tab, where the same
        branch is inverted and returns the complement of its label (filed as
        Canusia/package-cis#18). Matching that bug here would make the filter
        and Export All misreport what they selected, which is the failure this
        page exists to avoid.
        """
        self.assertEqual(self._feed_ids(record_type='with_prereq'),
                         {str(self.fall_reg.id)})

    def test_campus_filter(self):
        self.assertEqual(self._feed_ids(campus=str(self.campus_a.id)),
                         {str(self.fall_reg.id)})
        self.assertEqual(self._feed_ids(campus=str(self.campus_b.id)),
                         {str(self.spring_reg.id)})

    def test_unknown_record_type_returns_no_rows(self):
        # 'sis_error' is off the dropdown now, but the value still arrives from
        # a bookmarked or hand-typed URL, and apply_filters has no branch for
        # it -- so it used to read as applied and return everything.
        self.assertEqual(self._feed_ids(record_type='sis_error'), set())
        self.assertEqual(self._export_names(record_type='sis_error'), set())

    def test_malformed_campus_returns_no_rows_instead_of_500(self):
        # Matches the term filter. Dropping the filter instead would render a
        # full table the admin reads as scoped to one campus, and Export All
        # would carry that misreading out to CSV.
        self.assertEqual(self._feed_ids(campus='not-a-uuid'), set())

    def test_malformed_campus_empties_the_export_too(self):
        self.assertEqual(self._export_names(campus='not-a-uuid'), set())

    def test_filters_combine(self):
        self.assertEqual(
            self._feed_ids(term=str(self.fall.id), status='applied'), set())
        self.assertEqual(
            self._feed_ids(term=str(self.fall.id), status='approved'),
            {str(self.fall_reg.id)})

    # --- the export follows the same filters --------------------------------

    def test_export_all_honors_the_filter_bar(self):
        self.assertEqual(self._export_names(), {'Student, fmffall',
                                                'Student, fmfspring'})
        self.assertEqual(self._export_names(term=str(self.fall.id)),
                         {'Student, fmffall'})
        self.assertEqual(self._export_names(campus=str(self.campus_b.id)),
                         {'Student, fmfspring'})
