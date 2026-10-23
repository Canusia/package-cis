"""Term forms in multi-campus mode (#113): each academic year / term option
shows its campus, the lists are limited to the user's campuses (+ null), a
parent must be on the term's campus, and the term/academic-year detail pages
are campus-gated. Single-campus deployments keep the old labels and lists."""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.contrib.messages.storage.cookie import CookieStorage
from django.test import RequestFactory, TestCase, override_settings

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.forms.term import (
    BulkAssignParentForm, MigrateAcademicYearForm, MigrateTermForm, TermForm,
)
from cis.models.course import Campus
from cis.models.term import AcademicYear, Term

User = get_user_model()
multi = override_settings(MULTI_CAMPUS=True)
single = override_settings(MULTI_CAMPUS=False)


def _sfx():
    return uuid.uuid4().hex[:8]


def _labels(field):
    return [label for value, label in field.choices if value]


class TermFormCampusTests(TestCase):
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
        prefix = settings.CAMPUS_CODE_PREFIX
        self.campus_a = Campus.objects.create(name=f'A-{_sfx()}', code=f'{prefix}-{_sfx()}')
        self.campus_b = Campus.objects.create(name=f'B-{_sfx()}', code=f'{prefix}-{_sfx()}')
        # Two campuses' years share a name -- the case #113 is about.
        self.year = f'2026-{_sfx()}'
        self.ay_a = AcademicYear.objects.create(name=self.year, campus=self.campus_a)
        self.ay_b = AcademicYear.objects.create(name=self.year, campus=self.campus_b)
        self.term_a = Term.objects.create(academic_year=self.ay_a, code=f'A{_sfx()}', label='Fall')
        self.term_a2 = Term.objects.create(academic_year=self.ay_a, code=f'A{_sfx()}', label='Spring')
        self.term_b = Term.objects.create(academic_year=self.ay_b, code=f'B{_sfx()}', label='Fall')

        self.ce = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.ce.save()
        self.ce.set_process_campuses([str(self.campus_a.id)])

    def _data(self, term, **over):
        data = {'academic_year': str(term.academic_year_id),
                'code': term.code, 'label': term.label}
        data.update(over)
        return data

    # --- labels -----------------------------------------------------------

    @multi
    def test_academic_year_labels_show_campus(self):
        labels = _labels(TermForm().fields['academic_year'])
        self.assertIn(f'{self.year} ({self.campus_a.name})', labels)
        self.assertIn(f'{self.year} ({self.campus_b.name})', labels)

    @multi
    def test_parent_labels_show_campus_and_keep_tree(self):
        labels = _labels(TermForm().fields['parent'])
        self.assertIn(f'{self.term_a} ({self.campus_a.name})', labels)

    @single
    def test_single_campus_labels_unchanged(self):
        form = TermForm(user=self.ce)
        self.assertIn(self.year, _labels(form.fields['academic_year']))
        self.assertNotIn(f'{self.year} ({self.campus_a.name})',
                         _labels(form.fields['academic_year']))
        # Single campus stays unfiltered (#113 decision).
        self.assertIn(self.ay_b, form.fields['academic_year'].queryset)

    # --- scoping ----------------------------------------------------------

    @multi
    def test_ce_user_sees_only_own_campus(self):
        form = TermForm(user=self.ce)
        self.assertIn(self.ay_a, form.fields['academic_year'].queryset)
        self.assertNotIn(self.ay_b, form.fields['academic_year'].queryset)
        self.assertNotIn(self.term_b, form.fields['parent'].queryset)

    @multi
    def test_other_campus_year_rejected_on_post(self):
        form = TermForm(self._data(self.term_a, academic_year=str(self.ay_b.id)),
                        instance=self.term_a, user=self.ce)
        self.assertFalse(form.is_valid())
        self.assertIn('academic_year', form.errors)

    @multi
    def test_edit_limits_parents_to_own_campus(self):
        form = TermForm(instance=self.term_a)
        self.assertIn(self.term_a2, form.fields['parent'].queryset)
        self.assertNotIn(self.term_b, form.fields['parent'].queryset)

    # --- cross-campus parent ----------------------------------------------

    @multi
    def test_add_rejects_parent_from_other_campus(self):
        form = TermForm({'academic_year': str(self.ay_a.id), 'code': f'N{_sfx()}',
                         'label': 'New', 'parent': str(self.term_b.id)})
        self.assertFalse(form.is_valid())
        self.assertIn('parent', form.errors)

    @multi
    def test_add_allows_parent_on_same_campus(self):
        form = TermForm({'academic_year': str(self.ay_a.id), 'code': f'N{_sfx()}',
                         'label': 'New', 'parent': str(self.term_a.id)})
        self.assertTrue(form.is_valid(), form.errors.as_json())

    @single
    def test_single_campus_allows_any_parent(self):
        form = TermForm({'academic_year': str(self.ay_a.id), 'code': f'N{_sfx()}',
                         'label': 'New', 'parent': str(self.term_b.id)})
        self.assertTrue(form.is_valid(), form.errors.as_json())

    @multi
    def test_edit_checks_parent_against_newly_chosen_year(self):
        # Superuser-style (no user) form: the year changes to campus B while
        # the parent stays on A -- clean() compares with the posted year.
        self.term_a2.parent = self.term_a
        self.term_a2.save()
        form = TermForm(self._data(self.term_a2, academic_year=str(self.ay_b.id),
                                   parent=str(self.term_a.id)),
                        instance=self.term_a2)
        self.assertFalse(form.is_valid())
        self.assertIn('parent', form.errors)

    @multi
    def test_moving_parent_term_to_other_campus_keeps_sub_terms_together(self):
        self.term_a2.parent = self.term_a
        self.term_a2.save()
        form = TermForm(self._data(self.term_a, academic_year=str(self.ay_b.id)),
                        instance=self.term_a)
        self.assertFalse(form.is_valid())
        self.assertIn('academic_year', form.errors)

    @multi
    def test_options_grouped_by_campus(self):
        labels = _labels(TermForm().fields['academic_year'])
        a = [i for i, l in enumerate(labels) if l.endswith(f'({self.campus_a.name})')]
        b = [i for i, l in enumerate(labels) if l.endswith(f'({self.campus_b.name})')]
        self.assertLess(max(a), min(b))

    @multi
    def test_labels_render_without_per_option_queries(self):
        for i in range(5):
            Term.objects.create(academic_year=self.ay_a, code=f'X{i}{_sfx()}', label=f'X{i}')
        form = TermForm(user=self.ce)
        with self.assertNumQueries(1):
            _labels(form.fields['academic_year'])
        # Parent choices are built eagerly by apply_term_tree, in __init__.
        with self.assertNumQueries(0):
            _labels(form.fields['parent'])

    # --- migrate + bulk forms ---------------------------------------------

    @multi
    def test_migrate_destinations_stay_on_record_campus(self):
        ay_a2 = AcademicYear.objects.create(name=f'2027-{_sfx()}', campus=self.campus_a)
        ay_qs = MigrateAcademicYearForm(record=self.ay_a).fields['destination_record'].queryset
        self.assertIn(ay_a2, ay_qs)
        self.assertNotIn(self.ay_b, ay_qs)
        term_qs = MigrateTermForm(record=self.term_a).fields['destination_record'].queryset
        self.assertIn(self.term_a2, term_qs)
        self.assertNotIn(self.term_b, term_qs)

    @multi
    def test_bulk_assign_skips_other_campus_terms(self):
        form = BulkAssignParentForm(
            [self.term_a2.id, self.term_b.id], data={'parent': str(self.term_a.id)})
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertEqual(form.save(), (1, 1))
        self.term_a2.refresh_from_db()
        self.term_b.refresh_from_db()
        self.assertEqual(self.term_a2.parent_id, self.term_a.id)
        self.assertIsNone(self.term_b.parent_id)

    @multi
    def test_bulk_assign_skips_terms_outside_user_campuses(self):
        form = BulkAssignParentForm(
            [self.term_b.id], data={'parent': str(self.term_a.id)}, user=self.ce)
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertEqual(form.save(), (0, 1))

    # --- every caller passes the user -------------------------------------

    def _request(self, method='get', data=None):
        request = getattr(RequestFactory(), method)('/x', data or {})
        request.user = self.ce
        request.session = {}
        request._messages = CookieStorage(request)
        return request

    @multi
    def test_tabs_and_actions_pass_user(self):
        from cis.actions.term import assign_parent
        from cis.tabs.academic_year import migrate_tab as ay_migrate_tab
        from cis.tabs.term import details_tab, migrate_tab

        form = details_tab(self._request(), self.term_a)['form']
        self.assertNotIn(self.ay_b, form.fields['academic_year'].queryset)
        form = migrate_tab(self._request(), self.term_a)['migration_form']
        self.assertNotIn(self.term_b, form.fields['destination_record'].queryset)
        with self.settings(MULTI_CAMPUS=False):  # MC-09 refuses it otherwise
            ay_null = AcademicYear.objects.create(name=f'N-{_sfx()}', campus=None)
        form = ay_migrate_tab(self._request(), ay_null)['migration_form']
        self.assertNotIn(self.ay_b, form.fields['destination_record'].queryset)

        response = assign_parent(self._request(
            'post', {'ids[]': [str(self.term_a.id)]}))
        self.assertNotIn(str(self.term_b.id), response.content.decode())

    # --- detail pages are campus-gated ------------------------------------

    @multi
    def test_detail_pages_deny_other_campus(self):
        from cis.views.academic_year import detail as ay_detail
        from cis.views.term import detail as term_detail
        from cis.views.term import tab as term_tab
        self.assertEqual(term_detail(self._request(), record_id=self.term_b.id).status_code, 403)
        self.assertEqual(term_tab(self._request(), self.term_b.id, 'details').status_code, 403)
        self.assertEqual(ay_detail(self._request(), record_id=self.ay_b.id).status_code, 403)
        from cis.views.academic_year import tab as ay_tab
        self.assertEqual(ay_tab(self._request(), self.ay_b.id, 'details').status_code, 403)

    @single
    def test_single_campus_detail_not_gated(self):
        from cis.campus_gate import deny_other_campus
        self.assertIsNone(deny_other_campus(self._request(), self.campus_b))

