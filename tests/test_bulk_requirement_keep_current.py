"""#58: bulk "Update Status/Required" on course document and app requirements.

Both bulk forms used to require New Status and Required, and because
STATUS_OPTIONS has no blank entry the status silently defaulted to Active --
so flipping only Required re-activated every Inactive row selected. Pinned:

  - each field starts on "Keep current" and is written only when chosen;
  - choosing nothing is a form-level validation error that writes nothing,
    and the action surfaces that error as its message (the modal's JS has no
    input to pin an `__all__` error to);
  - the rendered modal has "Keep current" selected for both fields.
"""
import json
import re
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse

from cis.forms.course import (
    NOTHING_TO_UPDATE,
    BulkAppRequirementUpdateForm,
    BulkCourseDocumentRequirementUpdateForm,
)
from cis.models.course import (
    Campus, Cohort, Course, CourseAppRequirement, CourseDocumentRequirement,
)

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

YES, NO = '1', '2'


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


def _make_ce_user(campus):
    user = User.objects.create_user(
        username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
    user.groups.add(Group.objects.get_or_create(name='ce')[0])
    user.save()
    user.set_process_campuses([str(campus.id)])
    return user


def _selected_option(html, name):
    """The <option> marked selected inside <select name="{name}">, or None."""
    match = re.search(
        rf'<select[^>]*name="{name}"[^>]*>(.*?)</select>', html, re.S)
    assert match, f'no <select name="{name}"> in modal'
    selected = re.search(
        r'<option value="([^"]*)"[^>]*\bselected\b[^>]*>([^<]*)</option>',
        match.group(1))
    return selected.groups() if selected else None


class _BulkKeepCurrentCases:
    """Shared cases; subclasses set model, form_class, action and _make_req."""

    model = None
    form_class = None
    action = None

    def setUp(self):
        self.campus = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.course_a = Course.objects.create(
            catalog_number='101', title='A', cohort=cohort, campus=self.campus)
        self.course_b = Course.objects.create(
            catalog_number='102', title='B', cohort=cohort, campus=self.campus)

        # One Active/required row and one Inactive/not-required row, so a
        # write of either field's old default would show on one of them.
        self.active = self._make_req(self.course_a, status='Active', required=YES)
        self.inactive = self._make_req(self.course_b, status='Inactive', required=NO)
        self.reqs = [self.active, self.inactive]

    # -- helpers ----------------------------------------------------------

    def _form(self, **fields):
        data = QueryDict(mutable=True)
        data.setlist('record_ids', [str(r.id) for r in self.reqs])
        data.update({'action': self.action, **fields})
        return self.form_class(data=data)

    def _save(self, **fields):
        form = self._form(**fields)
        self.assertTrue(form.is_valid(), form.errors.as_json())
        form.save()
        for req in self.reqs:
            req.refresh_from_db()

    def _state(self):
        return {
            r.id: (r.status, r.required)
            for r in self.model.objects.filter(id__in=[r.id for r in self.reqs])
        }

    # -- save() -----------------------------------------------------------

    def test_only_required_leaves_status_unchanged(self):
        self._save(new_status='', new_required=YES)
        self.assertEqual(self.active.status, 'Active')
        self.assertEqual(self.inactive.status, 'Inactive')  # not re-activated
        self.assertEqual(self.active.required, YES)
        self.assertEqual(self.inactive.required, YES)

    def test_only_status_leaves_required_unchanged(self):
        self._save(new_status='Inactive', new_required='')
        self.assertEqual(self.active.status, 'Inactive')
        self.assertEqual(self.inactive.status, 'Inactive')
        self.assertEqual(self.active.required, YES)
        self.assertEqual(self.inactive.required, NO)

    def test_omitted_fields_count_as_keep_current(self):
        self._save(new_required=NO)
        self.assertEqual(self.inactive.status, 'Inactive')
        self.assertEqual(self.active.status, 'Active')
        self.assertEqual(self.active.required, NO)

    def test_both_updates_both(self):
        self._save(new_status='Active', new_required=NO)
        for req in self.reqs:
            self.assertEqual((req.status, req.required), ('Active', NO))

    def test_neither_is_a_form_error_and_writes_nothing(self):
        before = self._state()
        form = self._form(new_status='', new_required='')
        self.assertFalse(form.is_valid())
        self.assertEqual(form.non_field_errors(), [NOTHING_TO_UPDATE])
        self.assertEqual(self._state(), before)

    def test_keep_current_is_the_first_choice(self):
        form = self.form_class([str(r.id) for r in self.reqs])
        for name in ('new_status', 'new_required'):
            self.assertEqual(
                form.fields[name].choices[0], ('', 'Keep current'), name)
            self.assertFalse(form.fields[name].required, name)

    # -- the bulk action --------------------------------------------------

    def _login(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(_make_ce_user(self.campus))

    def _post(self, **extra):
        return self.client.post(reverse('cis:course_bulk_actions'), {
            'action': self.action,
            'ids[]': [str(r.id) for r in self.reqs],
            **extra,
        })

    def test_action_neither_returns_400_with_form_error_message(self):
        self._login()
        before = self._state()
        resp = self._post(action_confirmed='1', new_status='', new_required='')
        self.assertEqual(resp.status_code, 400, resp.content)
        body = resp.json()
        self.assertEqual(body['message'], NOTHING_TO_UPDATE)
        self.assertIn('__all__', json.loads(body['errors']))
        self.assertEqual(self._state(), before)

    def test_action_only_required_keeps_inactive_rows_inactive(self):
        self._login()
        resp = self._post(action_confirmed='1', new_status='', new_required=YES)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.inactive.refresh_from_db()
        self.assertEqual((self.inactive.status, self.inactive.required),
                         ('Inactive', YES))

    def test_modal_shows_keep_current_selected_for_both_fields(self):
        self._login()
        resp = self._post()
        self.assertEqual(resp.status_code, 200, resp.content)
        html = resp.json()['html']
        for name in ('new_status', 'new_required'):
            self.assertEqual(
                _selected_option(html, name), ('', 'Keep current'), name)


class BulkAppRequirementKeepCurrentTests(
        _NoLoginHistoryMixin, _BulkKeepCurrentCases, TestCase):
    model = CourseAppRequirement
    form_class = BulkAppRequirementUpdateForm
    action = 'update_app_requirements'

    def _make_req(self, course, **fields):
        return CourseAppRequirement.objects.create(
            course=course, name=f'Req-{_sfx()}', **fields)


class BulkCourseDocumentRequirementKeepCurrentTests(
        _NoLoginHistoryMixin, _BulkKeepCurrentCases, TestCase):
    model = CourseDocumentRequirement
    form_class = BulkCourseDocumentRequirementUpdateForm
    action = 'update_course_doc_requirements'

    def _make_req(self, course, **fields):
        return CourseDocumentRequirement.objects.create(
            course=course, document='transcript', **fields)

    def test_only_recurrence_is_a_valid_choice(self):
        """Recurrence alone counts as "something chosen" and touches nothing else."""
        self._save(new_status='', new_required='', new_recurrence='once')
        self.assertEqual(
            [(r.status, r.required, r.recurrence) for r in self.reqs],
            [('Active', YES, 'once'), ('Inactive', NO, 'once')])

    def test_modal_shows_keep_current_selected_for_recurrence(self):
        self._login()
        html = self._post().json()['html']
        self.assertEqual(
            _selected_option(html, 'new_recurrence'), ('', 'Keep current'))
