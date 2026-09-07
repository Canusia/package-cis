"""Course Document Requirements: the tenant seam, the grade semantics, and the UI.

Covers the things that could silently regress:

  - the model's `document`/`grade_levels` choices stay *callables*, so a tenant
    relabeling its vocabulary never writes a migration into shared `cis`;
  - `document` resolves through the **opt-in** seam
    (`get_tenant_override('course_document_types', 'choices')`), so a tenant that
    has not shipped the module keeps working on DEFAULT_DOCUMENT_TYPES;
  - blank `grade_levels` means *all grades*, and `applies_to_grade()` is the one
    place that lives;
  - display goes through `document_label`, never the raw stored code;
  - campus scoping on the viewset and on the bulk action's confirmed pass.
"""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.db import IntegrityError, transaction
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse

from cis.models.course import (
    Campus,
    Cohort,
    Course,
    CourseDocumentRequirement,
    DEFAULT_DOCUMENT_TYPES,
    course_document_choices,
    student_grade_choices,
)
from cis.models.student import Student
from cis.views.course import CourseDocumentRequirementViewSet

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

# A tenant app that has *not* adopted course_document_types: `cis.services`
# exists but ships no such module, which is exactly the opt-in seam's fallback
# case (get_tenant_override returns None rather than raising).
UNADOPTED_TENANT_APP = 'cis'


def _sfx():
    return uuid.uuid4().hex[:8]


class _NoLoginHistoryMixin:
    """django_login_history's post_login receiver crashes on force_login's bare
    request. Same disconnect the other cis tab/scope tests use."""

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


def _make_ce_user(campus=None):
    user = User.objects.create_user(
        username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
    user.groups.add(Group.objects.get_or_create(name='ce')[0])
    if campus is not None:
        user.campus = {'process_campus': [str(campus.id)]}
    user.save()
    return user


def _make_course(catalog_number='101', campus=None):
    cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
    return Course.objects.create(
        catalog_number=catalog_number, title=f'T-{_sfx()}',
        name=f'C-{_sfx()}', cohort=cohort, campus=campus, status='Active')


class CourseDocumentFieldChoicesTests(TestCase):
    """The migration-churn guard: the fields must keep the callable itself."""

    def test_document_field_keeps_the_callable_not_the_labels(self):
        field = CourseDocumentRequirement._meta.get_field('document')
        _, _, _, kwargs = field.deconstruct()

        self.assertTrue(callable(kwargs['choices']))
        self.assertIs(kwargs['choices'], course_document_choices)

    def test_grade_levels_field_keeps_the_callable_not_the_labels(self):
        field = CourseDocumentRequirement._meta.get_field('grade_levels')
        _, _, _, kwargs = field.deconstruct()

        self.assertTrue(callable(kwargs['choices']))
        self.assertIs(kwargs['choices'], student_grade_choices)


@override_settings(TENANT_SERVICES_APP='cis.tests.fake_tenant')
class TenantOverriddenVocabularyTests(TestCase):
    """With a tenant module present, the seam yields that tenant's vocabulary."""

    def test_choices_come_from_the_tenant_service(self):
        from cis.services.tenant_services import get_tenant_service

        self.assertEqual(course_document_choices(),
                         get_tenant_service('course_document_types').choices())

    def test_choices_are_the_fixture_vocabulary(self):
        self.assertEqual(
            course_document_choices(),
            [('doc_a', 'Document A'), ('doc_b', 'Document B'),
             ('doc_c', 'Document C')])

    def test_document_label_uses_the_tenant_label_for(self):
        req = CourseDocumentRequirement.objects.create(
            course=_make_course(), document='doc_b')

        self.assertEqual(req.document_label, 'Document B')

    def test_unknown_code_degrades_to_the_code(self):
        req = CourseDocumentRequirement.objects.create(
            course=_make_course(), document='retired_doc')

        self.assertEqual(req.document_label, 'retired_doc')


@override_settings(TENANT_SERVICES_APP=UNADOPTED_TENANT_APP)
class UnadoptedTenantFallbackTests(TestCase):
    """A tenant shipping no course_document_types keeps the cis defaults.

    This is why `document` uses get_tenant_override rather than
    get_tenant_service: the required-module form would break the course pages of
    every tenant that adopts this version before writing its own module.
    """

    def test_override_resolves_to_none(self):
        from cis.services.tenant_services import get_tenant_override

        self.assertIsNone(
            get_tenant_override('course_document_types', 'choices'))

    def test_choices_fall_back_to_the_cis_defaults(self):
        self.assertEqual(course_document_choices(), list(DEFAULT_DOCUMENT_TYPES))

    def test_document_label_falls_back_to_the_default_vocabulary(self):
        req = CourseDocumentRequirement.objects.create(
            course=_make_course(), document='transcript')

        self.assertEqual(req.document_label, 'High School Transcript')

    def test_unknown_code_returns_the_code_rather_than_raising(self):
        req = CourseDocumentRequirement.objects.create(
            course=_make_course(), document='retired_doc')

        self.assertEqual(req.document_label, 'retired_doc')


class StudentGradeChoicesTests(TestCase):
    def test_drops_the_blank_sentinel(self):
        self.assertEqual(
            student_grade_choices(),
            [(code, label) for code, label in Student.GRADE_LEVEL if code])

    def test_no_blank_code_entry_survives(self):
        self.assertNotIn('', [code for code, _ in student_grade_choices()])
        self.assertTrue(student_grade_choices())


class AppliesToGradeTests(TestCase):
    def setUp(self):
        self.course = _make_course()

    def test_blank_grade_levels_means_all_grades(self):
        req = CourseDocumentRequirement.objects.create(
            course=self.course, document='transcript')

        self.assertEqual(list(req.grade_levels), [])
        for code, _label in student_grade_choices():
            self.assertTrue(req.applies_to_grade(code),
                            f'{code} should be in scope when unscoped')

    def test_unscoped_labels_read_as_all_grades(self):
        req = CourseDocumentRequirement.objects.create(
            course=self.course, document='transcript')

        self.assertEqual(req.grade_level_labels, ['All grades'])

    def test_populated_grade_levels_scope_the_requirement(self):
        codes = [code for code, _ in student_grade_choices()]
        listed, unlisted = codes[:1], codes[1:]
        req = CourseDocumentRequirement.objects.create(
            course=self.course, document='tsi', grade_levels=listed)

        for code in listed:
            self.assertTrue(req.applies_to_grade(code))
        for code in unlisted:
            self.assertFalse(req.applies_to_grade(code))

    def test_scoped_labels_are_the_listed_grade_labels(self):
        labels = dict(student_grade_choices())
        codes = [code for code, _ in student_grade_choices()][:2]
        req = CourseDocumentRequirement.objects.create(
            course=self.course, document='tsi', grade_levels=codes)

        self.assertEqual(req.grade_level_labels, [labels[c] for c in codes])


class UniqueTogetherTests(TestCase):
    def setUp(self):
        self.course = _make_course()
        self.other_course = _make_course(catalog_number='202')
        CourseDocumentRequirement.objects.create(
            course=self.course, document='transcript')

    def test_same_document_twice_on_one_course_is_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CourseDocumentRequirement.objects.create(
                    course=self.course, document='transcript')

    def test_same_document_on_another_course_is_fine(self):
        req = CourseDocumentRequirement.objects.create(
            course=self.other_course, document='transcript')

        self.assertIsNotNone(req.pk)
        self.assertEqual(
            CourseDocumentRequirement.objects.filter(
                document='transcript').count(), 2)


@override_settings(TENANT_SERVICES_APP='cis.tests.fake_tenant')
class DocumentRequirementsTabTests(_NoLoginHistoryMixin, TestCase):
    def setUp(self):
        self.user = _make_ce_user()
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.user)
        self.course = _make_course()
        self.req = CourseDocumentRequirement.objects.create(
            course=self.course, document='doc_a', description='Bring it')

    def _tab_url(self):
        return reverse('cis:course_tab',
                       args=[self.course.id, 'document_requirements'])

    def test_tab_renders_the_label_not_the_raw_code(self):
        resp = self.client.get(self._tab_url())

        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('Document A', body)
        self.assertIn("name=\"action\" value='save_course_doc_req'", body)

    def test_edit_link_round_trips_the_requirement_id(self):
        resp = self.client.get(self._tab_url())
        body = resp.content.decode()

        self.assertIn(f'?course_doc_id={self.req.id}', body)

    def test_course_doc_id_prepopulates_the_form(self):
        resp = self.client.get(self._tab_url(),
                               {'course_doc_id': str(self.req.id)})

        self.assertEqual(resp.status_code, 200)
        form = resp.context['course_doc_req_form']
        self.assertEqual(form.instance.pk, self.req.pk)
        self.assertEqual(form.initial['document'], 'doc_a')

    def test_without_course_doc_id_the_form_is_a_fresh_instance(self):
        resp = self.client.get(self._tab_url())

        form = resp.context['course_doc_req_form']
        # The model's id defaults to uuid4(), so an unsaved instance already
        # carries a pk — 'unsaved' is _state.adding, not a null pk.
        self.assertTrue(form.instance._state.adding)
        self.assertNotEqual(form.instance.pk, self.req.pk)
        self.assertFalse(form.initial.get('document'))

    def test_detail_page_renders_the_tab_eagerly(self):
        resp = self.client.get(reverse('cis:course', args=[self.course.id]))

        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('href="#document_requirements"', body)
        self.assertIn('Document A', body)


class CourseDocumentRequirementViewSetScopeTests(_NoLoginHistoryMixin, TestCase):
    """ce user sees own-campus + null-campus rows only."""

    def setUp(self):
        self.rf = RequestFactory()
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')

        self.course_a = _make_course('101', self.campus_a)
        self.course_b = _make_course('201', self.campus_b)
        self.course_none = _make_course('100', None)

        self.req_a = CourseDocumentRequirement.objects.create(
            course=self.course_a, document='transcript')
        self.req_b = CourseDocumentRequirement.objects.create(
            course=self.course_b, document='transcript')
        self.req_none = CourseDocumentRequirement.objects.create(
            course=self.course_none, document='transcript')

        self.user = _make_ce_user(self.campus_a)

    def _queryset(self):
        req = self.rf.get('/ce/api/course-document-requirement')
        req.user = self.user
        vs = CourseDocumentRequirementViewSet()
        vs.request = req
        vs.format_kwarg = None
        return vs.get_queryset()

    def test_own_campus_and_null_campus_included(self):
        qs = self._queryset()
        self.assertIn(self.req_a, qs)
        self.assertIn(self.req_none, qs)

    def test_other_campus_excluded(self):
        qs = self._queryset()
        self.assertNotIn(self.req_b, qs)


class UpdateCourseDocRequirementsBulkGateTests(_NoLoginHistoryMixin, TestCase):
    """The confirmed pass of update_course_doc_requirements must drop
    out-of-scope ids, not just hide them from the modal."""

    def setUp(self):
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')

        self.course_a = _make_course('501', self.campus_a)
        self.course_b = _make_course('601', self.campus_b)

        self.req_a = CourseDocumentRequirement.objects.create(
            course=self.course_a, document='transcript', status='Active')
        self.req_b = CourseDocumentRequirement.objects.create(
            course=self.course_b, document='transcript', status='Active')

        self.user = _make_ce_user(self.campus_a)
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.user)

    def test_confirmed_bulk_update_skips_out_of_scope_requirement(self):
        resp = self.client.post(reverse('cis:course_bulk_actions'), {
            'action': 'update_course_doc_requirements',
            'action_confirmed': '1',
            'ids[]': [str(self.req_a.id), str(self.req_b.id)],
            'new_status': 'Inactive',
            'new_required': '1',
        })

        self.assertEqual(resp.status_code, 200, resp.content)
        self.req_a.refresh_from_db()
        self.req_b.refresh_from_db()
        self.assertEqual(self.req_a.status, 'Inactive')   # in scope: updated
        self.assertEqual(self.req_b.status, 'Active')     # out of scope: untouched


@override_settings(TENANT_SERVICES_APP='cis.tests.fake_tenant')
class AddCourseDocumentRequirementFormTests(TestCase):
    def setUp(self):
        self.course_a = _make_course('701')
        self.course_b = _make_course('801')

    def _form(self, courses, **overrides):
        from cis.forms.course import AddCourseDocumentRequirementForm

        data = {
            'courses': [str(c.id) for c in courses],
            'document': 'doc_a',
            'grade_levels': [],
            'description': 'Bring it',
            'required': '1',
            'status': 'Active',
            'action': 'add_course_doc_requirement',
        }
        data.update(overrides)
        return AddCourseDocumentRequirementForm(data=data)

    def test_creates_one_row_per_selected_course(self):
        form = self._form([self.course_a, self.course_b])
        self.assertTrue(form.is_valid(), form.errors.as_json())

        created = form.save()

        self.assertEqual(len(created), 2)
        self.assertEqual(CourseDocumentRequirement.objects.count(), 2)
        self.assertEqual(
            set(CourseDocumentRequirement.objects.values_list(
                'course_id', flat=True)),
            {self.course_a.id, self.course_b.id})

    def test_resubmitting_the_same_pair_updates_rather_than_duplicates(self):
        form = self._form([self.course_a])
        self.assertTrue(form.is_valid(), form.errors.as_json())
        first = form.save()[0]

        again = self._form([self.course_a], status='Inactive',
                           description='Updated')
        self.assertTrue(again.is_valid(), again.errors.as_json())
        second = again.save()[0]

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(CourseDocumentRequirement.objects.count(), 1)
        first.refresh_from_db()
        self.assertEqual(first.status, 'Inactive')
        self.assertEqual(first.description, 'Updated')

    def test_a_different_document_on_the_same_course_is_a_new_row(self):
        self._valid_save([self.course_a], 'doc_a')
        self._valid_save([self.course_a], 'doc_b')

        self.assertEqual(
            CourseDocumentRequirement.objects.filter(
                course=self.course_a).count(), 2)

    def _valid_save(self, courses, document):
        form = self._form(courses, document=document)
        self.assertTrue(form.is_valid(), form.errors.as_json())
        return form.save()

    def test_document_choices_come_from_the_tenant_vocabulary(self):
        from cis.forms.course import AddCourseDocumentRequirementForm

        form = AddCourseDocumentRequirementForm()

        self.assertEqual(list(form.fields['document'].choices),
                         course_document_choices())
        self.assertEqual(list(form.fields['grade_levels'].choices),
                         student_grade_choices())
