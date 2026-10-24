"""Academic years in multi-campus mode (#116): the campus dropdown lists only
the user's campuses, a year cannot be moved to another campus, and term /
academic-year deletes are campus-gated. Single-campus deployments are
unchanged."""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase, override_settings

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.forms.term import AcademicYearForm
from cis.models.course import Campus
from cis.models.term import AcademicYear, Term

User = get_user_model()
multi = override_settings(MULTI_CAMPUS=True)
single = override_settings(MULTI_CAMPUS=False)


def _sfx():
    return uuid.uuid4().hex[:8]


class AcademicYearCampusScopeTests(TestCase):
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
        self.ay_a = AcademicYear.objects.create(name=f'2026-{_sfx()}', campus=self.campus_a)
        self.ay_b = AcademicYear.objects.create(name=f'2026-{_sfx()}', campus=self.campus_b)
        self.term_b = Term.objects.create(academic_year=self.ay_b, code=f'B{_sfx()}', label='Fall')

        self.ce = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.ce.save()
        self.ce.set_process_campuses([str(self.campus_a.id)])

    def _year_data(self, campus):
        return {'name': self.ay_a.name, 'campus': str(campus.id),
                'hs_start_date': '08/01/2026', 'hs_end_date': '06/01/2027'}

    # --- form -------------------------------------------------------------

    @multi
    def test_campus_dropdown_lists_only_the_users_campuses(self):
        campuses = list(AcademicYearForm(user=self.ce).fields['campus'].queryset)
        self.assertIn(self.campus_a, campuses)
        self.assertNotIn(self.campus_b, campuses)

    @multi
    def test_year_cannot_be_moved_to_another_campus(self):
        form = AcademicYearForm(
            self._year_data(self.campus_b), instance=self.ay_a, user=self.ce)
        self.assertFalse(form.is_valid())
        self.assertIn('campus', form.errors)

    @multi
    def test_superuser_sees_every_campus(self):
        admin = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')
        campuses = list(AcademicYearForm(user=admin).fields['campus'].queryset)
        self.assertIn(self.campus_a, campuses)
        self.assertIn(self.campus_b, campuses)

    @single
    def test_single_campus_dropdown_is_unchanged(self):
        campuses = list(AcademicYearForm(user=self.ce).fields['campus'].queryset)
        self.assertIn(self.campus_b, campuses)

    # --- deletes ----------------------------------------------------------

    # Views are called directly: in multi-campus mode the campus middleware
    # refuses the test client's host before any view runs.
    def _call(self, view, record):
        from django.test import RequestFactory
        request = RequestFactory().post('/')
        request.user = self.ce
        return view(request, record.id)

    @multi
    def test_delete_year_on_another_campus_is_refused(self):
        from cis.views.academic_year import delete_record
        resp = self._call(delete_record, self.ay_b)
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(AcademicYear.objects.filter(pk=self.ay_b.pk).exists())

    @multi
    def test_delete_term_on_another_campus_is_refused(self):
        from cis.views.term import delete_record
        resp = self._call(delete_record, self.term_b)
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Term.objects.filter(pk=self.term_b.pk).exists())

    @multi
    def test_delete_year_on_own_campus_still_works(self):
        from cis.views.academic_year import delete_record
        resp = self._call(delete_record, self.ay_a)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(AcademicYear.objects.filter(pk=self.ay_a.pk).exists())

    @multi
    def test_bulk_delete_skips_years_on_another_campus(self):
        from cis.views.academic_year import delete_academic_years
        from django.test import RequestFactory

        request = RequestFactory().post('/', {'ids[]': [str(self.ay_a.id), str(self.ay_b.id)]})
        request.user = self.ce
        resp = delete_academic_years(request)
        self.assertIn(b'1 could not be deleted', resp.content)
        self.assertFalse(AcademicYear.objects.filter(pk=self.ay_a.pk).exists())
        self.assertTrue(AcademicYear.objects.filter(pk=self.ay_b.pk).exists())
