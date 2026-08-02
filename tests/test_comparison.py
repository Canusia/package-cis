"""Tests for the dimension-parameterized comparison tool.

Covers the registry, filter parsing + campus gate, the six metrics,
and the endpoint. Metric/gate tests run against BOTH dimensions so
academic-year support is proven, not assumed.
"""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.db.models import Q
from django.http import Http404
from django.test import RequestFactory, TestCase
from django.urls import reverse
from rest_framework.exceptions import ValidationError

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import Campus, Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.term import AcademicYear, Term
from cis.services.comparison import (
    COMPARE_DIMENSIONS, MAX_COMPARE_IDS, NO_CAMPUS, METRICS, NO_HIGH_SCHOOL,
    build_compare_context, build_payload, campus_q, get_dimension,
    parse_filters, run_metric,
)

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class DimensionRegistryTests(TestCase):
    def test_max_compare_ids_is_three(self):
        self.assertEqual(MAX_COMPARE_IDS, 3)

    def test_both_dimensions_registered(self):
        self.assertEqual(set(COMPARE_DIMENSIONS), {'term', 'academic_year'})

    def test_term_dimension_paths(self):
        dim = get_dimension('term')
        self.assertIs(dim.model, Term)
        self.assertEqual(dim.registration_path, 'class_section__term')
        self.assertEqual(dim.section_path, 'term')

    def test_academic_year_dimension_paths(self):
        dim = get_dimension('academic_year')
        self.assertIs(dim.model, AcademicYear)
        self.assertEqual(
            dim.registration_path, 'class_section__term__academic_year')
        self.assertEqual(dim.section_path, 'term__academic_year')

    def test_unknown_slug_raises_http404(self):
        with self.assertRaises(Http404):
            get_dimension('semester')

    def test_term_label_uses_str_not_label_field(self):
        """Term.label alone is ambiguous across years; __str__ disambiguates."""
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='202601', label='Fall')
        self.assertEqual(get_dimension('term').label(term), f'{ay.name}, Fall')

    def test_academic_year_label_uses_name_field(self):
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.assertEqual(get_dimension('academic_year').label(ay), ay.name)


def _make_campus(prefixed=True):
    prefix = settings.CAMPUS_CODE_PREFIX if prefixed else 'ZZ'
    return Campus.objects.create(name=f'C-{_sfx()}', code=f'{prefix}-{_sfx()}')


def _make_ce_user(*campuses):
    """A 'ce' user whose process_campus list is exactly `campuses`."""
    user = User.objects.create_user(
        username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
    user.groups.add(Group.objects.get_or_create(name='ce')[0])
    user.campus = {'process_campus': [str(c.id) for c in campuses]}
    user.save()
    return user


def _make_course(cohort, campus, catalog_number, title, credit_hours=3.0):
    return Course.objects.create(
        catalog_number=catalog_number, title=title, cohort=cohort,
        campus=campus, credit_hours=credit_hours)


def _make_section(term, course, highschool=None, status='A'):
    return ClassSection.objects.create(
        class_number=f'CN{_sfx()}', section_number='01',
        term=term, course=course, highschool=highschool, status=status)


def _make_registration(section, status='registered', student_highschool=None):
    user = User.objects.create_user(
        username=f'st_{_sfx()}', email=f'st_{_sfx()}@x.com', password='x')
    # Student.save() does Group.objects.get(name='student') unconditionally.
    Group.objects.get_or_create(name='student')
    # StudentRegistration's post_save signal calls Student.add_note(), which
    # falls back to CustomUser.objects.get(username='cron') when there is no
    # current request user (as in tests).
    User.objects.get_or_create(
        username='cron', defaults={'email': 'cron@x.com'})
    student = Student.objects.create(user=user, highschool=student_highschool)
    # status_changed_on is a JSONField with NO default -- must be passed.
    return StudentRegistration.objects.create(
        student=student, class_section=section, status=status,
        status_changed_on={})


class ComparisonFixtureMixin:
    """Two academic years, one term each, two campuses, one high school."""

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
        self.campus_a = _make_campus()
        self.campus_b = _make_campus()
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.hs_a = HighSchool.objects.create(name=f'HS-{_sfx()}')

        self.ay1 = AcademicYear.objects.create(name=f'AY1-{_sfx()}', code='2025')
        self.ay2 = AcademicYear.objects.create(name=f'AY2-{_sfx()}', code='2026')
        self.term1 = Term.objects.create(
            academic_year=self.ay1, code='202501', label='Fall')
        self.term2 = Term.objects.create(
            academic_year=self.ay2, code='202601', label='Fall')

        self.user = _make_ce_user(self.campus_a)

    def records_for(self, dim):
        """The two records of `dim` that the fixtures populate."""
        return (self.term1, self.term2) if dim.slug == 'term' \
            else (self.ay1, self.ay2)


class FixtureSmokeTests(ComparisonFixtureMixin, TestCase):
    def test_registration_saves_without_status_changed_on_default(self):
        course = _make_course(self.cohort, self.campus_a, '101', 'Intro')
        section = _make_section(self.term1, course, self.hs_a)
        reg = _make_registration(section)
        self.assertEqual(reg.status, 'registered')
        self.assertEqual(reg.class_section.term, self.term1)

    def test_records_for_maps_each_dimension(self):
        self.assertEqual(
            self.records_for(get_dimension('term')), (self.term1, self.term2))
        self.assertEqual(
            self.records_for(get_dimension('academic_year')),
            (self.ay1, self.ay2))


class ParseFiltersTests(ComparisonFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.rf = RequestFactory()

    def _parse(self, query, dim_slug='term', user=None):
        request = self.rf.get(f'/ce/api/comparison/{dim_slug}/', query)
        request.user = user or self.user
        return parse_filters(request, get_dimension(dim_slug))

    def test_defaults_when_no_params(self):
        f = self._parse({'id': str(self.term1.id)})
        self.assertEqual(f.section_statuses, ['A'])
        self.assertEqual(
            set(f.statuses),
            {v for v, _ in StudentRegistration.STATUS_OPTIONS})
        self.assertEqual(f.campus_ids, [str(self.campus_a.id)])
        self.assertTrue(f.include_null_campus)

    def test_ids_beyond_max_raise_400(self):
        term3 = Term.objects.create(
            academic_year=self.ay1, code='202502', label='Spring')
        with self.assertRaises(ValidationError):
            self._parse({'id': [str(self.term1.id), str(self.term2.id),
                                str(term3.id), str(uuid.uuid4())]})

    def test_unknown_status_raises_400(self):
        with self.assertRaises(ValidationError):
            self._parse({'id': str(self.term1.id), 'status': 'nonexistent'})

    def test_unknown_section_status_raises_400(self):
        with self.assertRaises(ValidationError):
            self._parse({'id': str(self.term1.id), 'section_status': 'X'})

    def test_non_uuid_id_is_dropped(self):
        f = self._parse({'id': ['not-a-uuid', str(self.term1.id)]})
        self.assertEqual(f.ids, [str(self.term1.id)])

    def test_out_of_gate_campus_dropped_silently(self):
        """User gated to campus_a asks for campus_b; b vanishes, no error."""
        f = self._parse({'id': str(self.term1.id),
                         'campus': str(self.campus_b.id)})
        self.assertEqual(f.campus_ids, [])
        self.assertFalse(f.include_null_campus)

    def test_explicit_none_campus_selects_null(self):
        f = self._parse({'id': str(self.term1.id), 'campus': NO_CAMPUS})
        self.assertEqual(f.campus_ids, [])
        self.assertTrue(f.include_null_campus)

    def test_non_ce_explicit_none_still_fails_closed(self):
        """A non-processing user asking for campus=none must not get nulls."""
        plain_user = User.objects.create_user(
            username=f'plain_{_sfx()}', email=f'plain_{_sfx()}@x.com',
            password='x')
        f = self._parse(
            {'id': str(self.term1.id), 'campus': NO_CAMPUS}, user=plain_user)
        self.assertFalse(f.include_null_campus)
        self.assertEqual(f.campus_ids, [])
        self.assertEqual(
            str(campus_q('course__campus', f)), str(Q(pk__in=[])))

    def test_campus_q_with_nothing_selected_matches_nothing(self):
        f = self._parse({'id': str(self.term1.id),
                         'campus': str(self.campus_b.id)})
        self.assertEqual(
            str(campus_q('course__campus', f)), str(Q(pk__in=[])))

    def test_non_ce_non_superuser_defaults_fail_closed(self):
        """No campus param, no CIS role, no superuser: must not expose nulls."""
        plain_user = User.objects.create_user(
            username=f'plain_{_sfx()}', email=f'plain_{_sfx()}@x.com',
            password='x')
        f = self._parse({'id': str(self.term1.id)}, user=plain_user)
        self.assertFalse(f.include_null_campus)
        self.assertEqual(f.campus_ids, [])
        self.assertEqual(
            str(campus_q('course__campus', f)), str(Q(pk__in=[])))

    def test_superuser_defaults_include_null_campus(self):
        superuser = User.objects.create_superuser(
            username=f'super_{_sfx()}', email=f'super_{_sfx()}@x.com',
            password='x')
        f = self._parse({'id': str(self.term1.id)}, user=superuser)
        self.assertTrue(f.include_null_campus)

    def test_uppercase_in_gate_campus_uuid_is_preserved(self):
        f = self._parse({'id': str(self.term1.id),
                         'campus': str(self.campus_a.id).upper()})
        self.assertEqual(f.campus_ids, [str(self.campus_a.id)])

    def test_dashless_in_gate_campus_uuid_is_preserved(self):
        f = self._parse({'id': str(self.term1.id),
                         'campus': str(self.campus_a.id).replace('-', '')})
        self.assertEqual(f.campus_ids, [str(self.campus_a.id)])


class MetricTests(ComparisonFixtureMixin, TestCase):
    """Metrics run against BOTH dimensions from one fixture set."""

    def setUp(self):
        super().setUp()
        self.rf = RequestFactory()
        self.course_a = _make_course(
            self.cohort, self.campus_a, '101', 'Intro', credit_hours=3.0)
        self.course_b = _make_course(
            self.cohort, self.campus_a, '201', 'Advanced', credit_hours=4.0)

        # term1: 2 registrations on course_a (1 registered, 1 dropped),
        #        1 registration on a CANCELLED section of course_b.
        # Students are enrolled at hs_a (the STUDENT's high school -- the
        # section's own highschool is a separate, unrelated field).
        self.sec1a = _make_section(self.term1, self.course_a, self.hs_a)
        _make_registration(self.sec1a, 'registered', student_highschool=self.hs_a)
        _make_registration(self.sec1a, 'dropped', student_highschool=self.hs_a)
        self.sec1b = _make_section(
            self.term1, self.course_b, self.hs_a, status='C')
        _make_registration(
            self.sec1b, 'registered', student_highschool=self.hs_a)

        # term2: 1 registration on course_a, section has NO high school and
        # the student ALSO has no high school.
        self.sec2a = _make_section(self.term2, self.course_a, highschool=None)
        _make_registration(self.sec2a, 'registered')

    def _filters(self, dim_slug, **extra):
        records = self.records_for(get_dimension(dim_slug))
        query = {'id': [str(r.id) for r in records]}
        query.update(extra)
        request = self.rf.get(f'/ce/api/comparison/{dim_slug}/', query)
        request.user = self.user
        return parse_filters(request, get_dimension(dim_slug))

    def _totals(self, rows):
        """Collapse rows to {category: summed value} across all dimensions."""
        out = {}
        for r in rows:
            out[r['category']] = out.get(r['category'], 0) + r['value']
        return out

    def _by_dimension(self, rows):
        """{dimension_id: {category: value}} -- preserves bucketing."""
        out = {}
        for r in rows:
            out.setdefault(r['dimension_id'], {})[r['category']] = r['value']
        return out

    def test_registrations_by_status_buckets_per_dimension_record(self):
        f = self._filters('term', status='registered')
        by_dim = self._by_dimension(run_metric(f, 'registrations_by_status'))
        self.assertEqual(by_dim, {
            str(self.term1.id): {'registered': 1},
            str(self.term2.id): {'registered': 1},
        })

    def test_academic_year_dimension_buckets_to_its_own_records(self):
        f = self._filters('academic_year', status='registered')
        by_dim = self._by_dimension(run_metric(f, 'registrations_by_status'))
        self.assertEqual(set(by_dim), {str(self.ay1.id), str(self.ay2.id)})
        self.assertEqual(by_dim[str(self.ay1.id)], {'registered': 1})
        self.assertEqual(by_dim[str(self.ay2.id)], {'registered': 1})

    def test_total_credits_buckets_per_dimension_record(self):
        f = self._filters('term', status='registered')
        by_dim = self._by_dimension(run_metric(f, 'total_credits'))
        self.assertEqual(by_dim, {
            str(self.term1.id): {'Total credits': 3.0},
            str(self.term2.id): {'Total credits': 3.0},
        })

    def test_all_six_metrics_registered_in_display_order(self):
        self.assertEqual(list(METRICS), [
            'registrations_by_status', 'registrations_by_highschool',
            'registrations_by_course', 'sections_by_course',
            'sections_by_highschool', 'total_credits',
        ])

    def test_registrations_by_status_both_dimensions(self):
        for slug in ('term', 'academic_year'):
            with self.subTest(dimension=slug):
                f = self._filters(slug, status=[
                    'registered', 'dropped'], section_status='A')
                totals = self._totals(
                    run_metric(f, 'registrations_by_status'))
                # Active sections only: sec1b's 'registered' reg is excluded.
                self.assertEqual(totals, {'registered': 2, 'dropped': 1})

    def test_section_status_filter_excludes_cancelled_registrations(self):
        f = self._filters('term', section_status=['A', 'C'])
        totals = self._totals(run_metric(f, 'registrations_by_status'))
        self.assertEqual(totals['registered'], 3)  # sec1b now included

    def test_status_filter_changes_counts(self):
        f = self._filters('term', status='registered')
        totals = self._totals(run_metric(f, 'registrations_by_status'))
        self.assertEqual(totals, {'registered': 2})

    def test_registrations_by_course_uses_catalog_and_title(self):
        f = self._filters('term', status='registered')
        totals = self._totals(run_metric(f, 'registrations_by_course'))
        self.assertEqual(totals, {'101 — Intro': 2})

    def test_null_highschool_groups_under_label(self):
        """A student with no high school groups under NO_HIGH_SCHOOL.

        This does NOT distinguish student-HS from section-HS: in this fixture
        both are hs_a. See test_registrations_by_highschool_uses_student_hs.
        """
        f = self._filters('term', status='registered')
        totals = self._totals(run_metric(f, 'registrations_by_highschool'))
        self.assertEqual(totals[NO_HIGH_SCHOOL], 1)
        self.assertEqual(totals[self.hs_a.name], 1)

    def test_registrations_by_highschool_uses_student_hs(self):
        """Group by the STUDENT's high school, not the section's teaching site.

        Fails under the old `class_section__highschool__` grouping, which would
        credit the registration to hs_a (where the section is taught).
        """
        hs_b = HighSchool.objects.create(name=f'HS-B-{_sfx()}')
        section_at_hs_a = _make_section(self.term1, self.course_a, self.hs_a)
        _make_registration(
            section_at_hs_a, 'registered', student_highschool=hs_b)

        f = self._filters('term', status='registered')
        totals = self._totals(run_metric(f, 'registrations_by_highschool'))

        self.assertEqual(totals[hs_b.name], 1)
        # hs_a keeps only its own student; it does not absorb hs_b's.
        self.assertEqual(totals[self.hs_a.name], 1)

    def test_sections_by_highschool_still_uses_section_hs(self):
        """A section has no student, so metric 5 keeps the section's own HS."""
        hs_b = HighSchool.objects.create(name=f'HS-B-{_sfx()}')
        section_at_hs_a = _make_section(self.term1, self.course_a, self.hs_a)
        _make_registration(
            section_at_hs_a, 'registered', student_highschool=hs_b)

        f = self._filters('term')
        totals = self._totals(run_metric(f, 'sections_by_highschool'))

        self.assertNotIn(hs_b.name, totals)
        self.assertEqual(totals[self.hs_a.name], 2)

    def test_sections_by_course_counts_active_only(self):
        f = self._filters('term')
        totals = self._totals(run_metric(f, 'sections_by_course'))
        self.assertEqual(totals, {'101 — Intro': 2})

    def test_sections_by_course_buckets_per_dimension_record(self):
        f = self._filters('term')
        by_dim = self._by_dimension(run_metric(f, 'sections_by_course'))
        self.assertEqual(by_dim, {
            str(self.term1.id): {'101 — Intro': 1},
            str(self.term2.id): {'101 — Intro': 1},
        })

    def test_sections_by_highschool_both_dimensions(self):
        for slug in ('term', 'academic_year'):
            with self.subTest(dimension=slug):
                f = self._filters(slug)
                totals = self._totals(run_metric(f, 'sections_by_highschool'))
                self.assertEqual(totals[self.hs_a.name], 1)
                self.assertEqual(totals[NO_HIGH_SCHOOL], 1)

    def test_total_credits_sums_credit_hours_of_selected_statuses(self):
        f = self._filters('term', status='registered')
        rows = run_metric(f, 'total_credits')
        # 2 registered regs on course_a (3.0 credits each), active sections.
        self.assertEqual(sum(r['value'] for r in rows), 6.0)

    def test_total_credits_follows_status_selection(self):
        f = self._filters('term', status=['registered', 'dropped'])
        rows = run_metric(f, 'total_credits')
        self.assertEqual(sum(r['value'] for r in rows), 9.0)

    def test_other_campus_excluded_even_when_requested(self):
        """CE user gated to campus_a cannot pull campus_b's numbers."""
        course_b_campus = _make_course(
            self.cohort, self.campus_b, '301', 'Other')
        sec = _make_section(self.term1, course_b_campus, self.hs_a)
        _make_registration(sec, 'registered')

        f = self._filters('term', status='registered',
                          campus=str(self.campus_b.id))
        self.assertEqual(run_metric(f, 'registrations_by_course'), [])

    def test_no_campus_rows_included_by_default_and_removable(self):
        course_none = _make_course(self.cohort, None, '401', 'NoCampus')
        sec = _make_section(self.term1, course_none, self.hs_a)
        _make_registration(sec, 'registered')

        default = self._totals(run_metric(
            self._filters('term', status='registered'),
            'registrations_by_course'))
        self.assertIn('401 — NoCampus', default)

        without_null = self._totals(run_metric(
            self._filters('term', status='registered',
                          campus=str(self.campus_a.id)),
            'registrations_by_course'))
        self.assertNotIn('401 — NoCampus', without_null)

    def test_build_payload_carries_labels_and_all_metrics(self):
        f = self._filters('term')
        payload = build_payload(f)
        self.assertEqual(
            [d['label'] for d in payload['dimensions']],
            [str(self.term1), str(self.term2)])
        self.assertEqual(set(payload['metrics']), set(METRICS))
        self.assertEqual(
            payload['metrics']['total_credits']['presentation'], 'chart')
        self.assertEqual(
            payload['metrics']['sections_by_course']['presentation'],
            'chart_and_table')


class ComparisonEndpointTests(ComparisonFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        course = _make_course(self.cohort, self.campus_a, '101', 'Intro')
        _make_registration(_make_section(self.term1, course, self.hs_a),
                           'registered')

    def _url(self, dim_slug):
        return reverse('cis:comparison_data', kwargs={'dimension': dim_slug})

    def test_json_response_for_both_dimensions(self):
        for slug in ('term', 'academic_year'):
            with self.subTest(dimension=slug):
                records = self.records_for(get_dimension(slug))
                resp = self.client.get(
                    self._url(slug), {'id': [str(r.id) for r in records]})
                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertEqual(len(body['dimensions']), 2)
                self.assertEqual(set(body['metrics']), set(METRICS))

    def test_unknown_dimension_returns_404(self):
        resp = self.client.get('/ce/api/comparison/semester/',
                               {'id': str(self.term1.id)})
        self.assertEqual(resp.status_code, 404)

    def test_fourth_id_returns_400(self):
        term3 = Term.objects.create(
            academic_year=self.ay1, code='202502', label='Spring')
        resp = self.client.get(self._url('term'), {'id': [
            str(self.term1.id), str(self.term2.id), str(term3.id),
            str(uuid.uuid4())]})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_status_returns_400(self):
        resp = self.client.get(
            self._url('term'),
            {'id': str(self.term1.id), 'status': 'nonexistent'})
        self.assertEqual(resp.status_code, 400)

    def test_non_cis_user_is_denied(self):
        """The `user_passes_test` wrapper in urls.py is the outer layer: it
        runs before the view (and thus before CIS_user_only) ever executes,
        so a non-CIS user is redirected (302 -> '/'), matching every other
        CE route in urls.py. The DRF permission class never gets a chance
        to return 401/403 for requests reaching this URL.
        """
        outsider = User.objects.create_user(
            username=f'x_{_sfx()}', email=f'x_{_sfx()}@x.com', password='x')
        self.client.force_login(outsider)
        resp = self.client.get(self._url('term'), {'id': str(self.term1.id)})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith('/?next='))

    def test_format_csv_is_no_longer_special_cased(self):
        """CSV export was removed along with its DRF renderer workaround.
        `?format=csv` is now just an unknown DRF format: content negotiation
        in APIView.initial() raises Http404 before the view body runs.
        """
        resp = self.client.get(
            self._url('term'),
            {'id': str(self.term1.id), 'format': 'csv'})
        self.assertEqual(resp.status_code, 404)
        self.assertNotEqual(resp.get('Content-Type'), 'text/csv')


class BuildCompareContextTests(ComparisonFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.rf = RequestFactory()

    def _context(self, slug):
        request = self.rf.get('/ce/terms/')
        request.user = self.user
        return build_compare_context(request, slug)

    def test_term_context_lists_terms_with_str_labels(self):
        ctx = self._context('term')
        self.assertEqual(ctx['compare_dimension'], 'term')
        self.assertEqual(ctx['compare_noun'], 'Term')
        labels = [r['label'] for r in ctx['compare_records']]
        self.assertIn(str(self.term1), labels)

    def test_academic_year_context_lists_years(self):
        ctx = self._context('academic_year')
        self.assertEqual(ctx['compare_noun'], 'Academic Year')
        labels = [r['label'] for r in ctx['compare_records']]
        self.assertIn(self.ay1.name, labels)

    def test_campuses_are_gated_and_end_with_no_campus_entry(self):
        ctx = self._context('term')
        ids = [c['id'] for c in ctx['compare_campuses']]
        self.assertIn(str(self.campus_a.id), ids)
        self.assertNotIn(str(self.campus_b.id), ids)  # outside the gate
        self.assertEqual(ids[-1], NO_CAMPUS)

    def test_status_choices_present(self):
        ctx = self._context('term')
        self.assertEqual(
            ctx['compare_statuses'],
            list(StudentRegistration.STATUS_OPTIONS))
        self.assertEqual(
            ctx['compare_section_statuses'], list(ClassSection.CLASS_STATUS))

    def test_metric_cards_match_metrics_registry(self):
        ctx = self._context('term')
        self.assertEqual(
            [key for key, _ in ctx['compare_metric_cards']], list(METRICS))


class IndexPageMountTests(ComparisonFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_terms_index_renders_compare_panel(self):
        resp = self.client.get(reverse('cis:terms'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="compare-panel"')
        self.assertContains(resp, 'data-dimension="term"')
        self.assertContains(resp, 'Compare Terms')

    def test_academic_years_index_renders_compare_panel(self):
        resp = self.client.get(reverse('cis:academic_years'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-dimension="academic_year"')
        self.assertContains(resp, 'Compare Academic Years')

    def test_each_page_renders_all_six_metric_cards(self):
        for url_name in ('cis:terms', 'cis:academic_years'):
            with self.subTest(page=url_name):
                resp = self.client.get(reverse(url_name))
                for key in METRICS:
                    self.assertContains(resp, f'data-metric="{key}"')
