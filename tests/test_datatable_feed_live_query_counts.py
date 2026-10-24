"""Live query-count gates for the CE DataTables feeds (package-cis#99).

``test_datatable_feed_query_counts`` gates each relation plan against the
*full* serializer on a bare queryset. That leaves two gaps nnu's in-tree gates
cover and the package did not:

* the request a CE table actually sends -- ``format=datatables``, action
  ``list`` -- which binds the slim serializer ``datatables_serializer()``
  chooses, not the full one; and
* the viewset's own ``get_queryset()``, filters and campus scoping included,
  with ``@eager_queryset`` applied the way DRF dispatch runs it.

So these drive ``ViewSet.as_view({'get': 'list'})`` end to end, at two page
sizes over the same fixture, and assert the second page size costs no more
queries than the first (beyond a documented per-row allowance). Differencing
two page sizes cancels the constant -- the datatables backend's two counts,
the prefetches, the campus gate -- and leaves only the per-row term, which is
the N+1 coming back.
"""

from unittest import mock

from django.contrib.auth.models import Group
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIRequestFactory, force_authenticate

from cis.models import CustomUser
from cis.models.section import ClassSection
from cis.tests.test_datatable_feed_query_counts import FeedFixture
from cis.views import eager


def _registration_marginal():
    """1 on a tenant that overrides has_recommendation, else 0.

    The override is tenant policy and wins over the annotation (see
    RegistrationFlagAnnotationTests), so it costs one EXISTS per row. The test
    tenant defines one; nnu does not, and gets the flat path.
    """
    from cis.models.section import _tenant_registration_override
    return 1 if _tenant_registration_override('has_recommendation') else 0


class LiveFeedMixin:
    PAGE = 5

    @classmethod
    def setUpTestData(cls):
        for _ in range(2 * cls.PAGE):
            registration = FeedFixture.build()
        # The section feeds default to the active term; one shared term lets
        # a single `term` param select every fixture row.
        cls.term = registration.class_section.term
        ClassSection.objects.update(term=cls.term, registration_term=cls.term)

        Group.objects.get_or_create(name='ce')
        cls.user = CustomUser.objects.create_superuser(
            username='live-feed', email='live-feed@example.com', password='x')
        cls.user.groups.add(Group.objects.get(name='ce'))

    def _list(self, basename, length, params=None):
        """(rows, queries) for one datatables list request."""
        from cis.urls import router_viewsets

        query = {'format': 'datatables', 'draw': '1', 'start': '0',
                 'length': str(length)}
        query.update(params or {})
        request = APIRequestFactory().get('/x', query)
        force_authenticate(request, user=self.user)
        view = router_viewsets[basename].as_view({'get': 'list'})
        with CaptureQueriesContext(connection) as captured:
            response = view(request)
            response.render()
        self.assertEqual(response.status_code, 200, basename)
        return len(response.data['data']), len(captured.captured_queries)

    def assertFlat(self, basename, params=None, marginal=0):
        few_rows, few = self._list(basename, self.PAGE, params)
        many_rows, many = self._list(basename, 2 * self.PAGE, params)
        self.assertEqual(
            (few_rows, many_rows), (self.PAGE, 2 * self.PAGE),
            f'{basename}: the fixture did not reach the feed')
        per_extra_row = (many - few) / (many_rows - few_rows)
        self.assertLessEqual(
            per_extra_row, marginal,
            f'{basename}: {few} queries for {few_rows} rows, {many} for '
            f'{many_rows} -- {per_extra_row:.1f} per extra row; the allowance '
            f'is {marginal}')


class LiveDatatablesFeedQueryCountTests(LiveFeedMixin, TestCase):
    """Every planned CE feed is flat in page size on the datatables path.

    Not here: class-registered (one campus per fixture graph, so it never
    returns more than one row; it shares class_section's plan and serializer),
    and course-notes, course-app-requirement, highschool-administrator and
    teacher_application_reviewers, which need a parent id or rows the fixture
    does not build. Their plans are still gated in
    test_datatable_feed_query_counts.
    """

    # (basename, needs the shared term)
    FEEDS = (
        ('class_section', True),
        ('class_section_notes', True),
        ('class_section_syllabi', True),
        ('teacher', False),
        ('teacher-course', False),
        ('teacher-notes', False),
        ('highschool-teacher', False),
        ('hs-administrator-position', False),
        ('course', False),
        ('course-uploads', False),
        ('course-document-requirement', False),
        ('course_administrator', False),
        ('student_recommendation', False),
        ('student_tuitionassistance', False),
        ('student_support_docs', False),
        ('student_agreement', False),
        ('parent_consent', False),
        ('campus_id', False),
        ('student-note', False),
    )

    def test_every_planned_feed_is_flat_in_page_size(self):
        for basename, needs_term in self.FEEDS:
            with self.subTest(feed=basename):
                params = {'term': str(self.term.pk)} if needs_term else None
                self.assertFlat(basename, params)

    def test_registration_feed_is_flat_but_for_the_tenant_override(self):
        self.assertFlat('registration', {'term': str(self.term.pk)},
                        marginal=_registration_marginal())

    def test_drop_request_feed_is_flat_but_for_the_tenant_override(self):
        self.assertFlat('drop_wd_req', {'term': str(self.term.pk)},
                        marginal=_registration_marginal())

    def test_registration_feeds_are_flat_without_a_tenant_override(self):
        """A tenant with no has_recommendation override (nnu) reads the
        annotation and pays nothing per row."""
        from cis.services import tenant_services

        original = tenant_services.get_tenant_override

        def no_recommendation_override(module, attr, *args, **kwargs):
            if (module, attr) == ('registration', 'has_recommendation'):
                return None
            return original(module, attr, *args, **kwargs)

        with mock.patch.object(tenant_services, 'get_tenant_override',
                               no_recommendation_override):
            self.assertEqual(_registration_marginal(), 0)
            for basename in ('registration', 'drop_wd_req'):
                with self.subTest(feed=basename):
                    self.assertFlat(basename, {'term': str(self.term.pk)})


class UnboundFeedPlanTests(LiveFeedMixin, TestCase):
    """/ce/students/ and /ce/highschools/ carry no ``@eager_queryset``.

    StudentViewSet costs two queries per row (user, high school) and
    HighSchoolViewSet one (district). The plans exist in cis.views.eager; the
    expected failures below turn into unexpected successes the day the
    decorators are added, which is the cue to drop the decorator here.
    """

    def _bound(self, viewset, plan):
        original = viewset.get_queryset
        return mock.patch.object(
            viewset, 'get_queryset', lambda view: plan(original(view)))

    def test_the_student_plan_makes_the_feed_flat(self):
        from cis.views.student import StudentViewSet
        with self._bound(StudentViewSet, eager.with_student_related):
            self.assertFlat('student')

    def test_the_highschool_plan_makes_the_feed_flat(self):
        from cis.views.highschool import HighSchoolViewSet
        with self._bound(HighSchoolViewSet, eager.with_highschool_related):
            self.assertFlat('highschool')

    def test_student_feed_is_flat(self):
        self.assertFlat('student')

    def test_highschool_feed_is_flat(self):
        self.assertFlat('highschool')
