"""#130: CE term pickers list only the current campus's terms.

campus_terms() is every term on a single-campus deployment and the current
campus's terms on a multi-campus one; the CE pages and forms that offered
Term.objects.all() now use it, so a forged term id from another campus fails
form validation too.
"""
import uuid

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.contrib.sites.models import Site
from django.http import QueryDict
from django.test import TestCase, override_settings
from django.urls import reverse

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.campus_context import NoCampusContext, campus_context, campus_terms
from cis.models.course import Campus
from cis.models.customuser import CustomUser
from cis.models.settings import Setting
from cis.models.term import AcademicYear, Term

REG_KEY = f'{settings.CAMPUS_CODE_PREFIX}_cis_registrations'


def _sfx():
    return uuid.uuid4().hex[:6]


def _campus(name, domain=None):
    site = Site.objects.create(domain=domain, name=domain) if domain else None
    return Campus.objects.create(
        name=f'{name}-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}', site=site)


def _term(campus, code, parent=None):
    year = (parent.academic_year if parent else
            AcademicYear.objects.create(name=f'AY-{_sfx()}', campus=campus))
    return Term.objects.create(
        academic_year=year, code=code, label=f'{code}-{_sfx()}', parent=parent)


class CampusTermsHelperTests(TestCase):
    def setUp(self):
        self.c1 = _campus('C1')
        self.c2 = _campus('C2')
        self.t1 = _term(self.c1, 'C1FA')
        self.t2 = _term(self.c2, 'C2FA')

    @override_settings(MULTI_CAMPUS=False)
    def test_single_campus_lists_every_term(self):
        self.assertTrue({self.t1, self.t2} <= set(campus_terms()))

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_lists_the_current_campus_only(self):
        with campus_context(self.c1):
            self.assertEqual(list(campus_terms()), [self.t1])
        self.assertEqual(list(campus_terms(self.c2)), [self.t2])

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_without_a_campus_raises(self):
        with self.assertRaises(NoCampusContext):
            list(campus_terms())


@override_settings(MULTI_CAMPUS=True)
class CampusTermPickerPageTests(TestCase):
    """The pages render inside the host's campus, as CampusMiddleware serves them."""

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
        self.host = f'a{_sfx()}.example.edu'
        self.c1 = _campus('C1', self.host)
        self.c2 = _campus('C2', f'b{_sfx()}.example.edu')
        self.t1 = _term(self.c1, 'C1FA')
        self.t1_sub = _term(self.c1, 'C1FA1', parent=self.t1)
        self.t2 = _term(self.c2, 'C2FA')
        for campus, term in ((self.c1, self.t1), (self.c2, self.t2)):
            Setting.objects.create(key=REG_KEY, campus=campus, value={
                'active_term': str(term.id), 'registration_terms': [str(term.id)]})

        self.user = CustomUser.objects.create_user(
            username=f'ce{_sfx()}', email=f'{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.user.save()
        self.user.set_process_campuses([str(self.c1.id), str(self.c2.id)])
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1', HTTP_HOST=self.host)
        self.client.force_login(self.user)

    def _get(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_class_sections_filters_list_only_this_campus(self):
        html = self._get(reverse('cis:sections'))
        # Sections, Notes and Syllabi filter forms.
        self.assertGreaterEqual(html.count(f'value="{self.t1.id}"'), 3)
        self.assertIn(f'value="{self.t1_sub.id}"', html)
        self.assertNotIn(str(self.t2.id), html)

    def test_registrations_page_lists_only_this_campus(self):
        html = self._get(reverse('cis:registrations'))
        self.assertIn(str(self.t1.id), html)
        self.assertNotIn(str(self.t2.id), html)

    def test_students_page_lists_only_this_campus(self):
        html = self._get(reverse('cis:students'))
        self.assertNotIn(str(self.t2.id), html)


@override_settings(MULTI_CAMPUS=True)
class CampusTermFormValidationTests(TestCase):
    def setUp(self):
        self.c1 = _campus('C1')
        self.c2 = _campus('C2')
        self.t1 = _term(self.c1, 'C1FA')
        self.t2 = _term(self.c2, 'C2FA')

    def _term_field_accepts(self, form_class, term, **kwargs):
        with campus_context(self.c1):
            form = form_class(**kwargs)
            field = form.fields[self._field]
            try:
                field.clean(str(term.id))
            except Exception:
                return False
            return True

    def test_add_registration_form_rejects_another_campus_term(self):
        from cis.forms.section import AddNewStudentRegistrationForm
        self._field = 'term'
        self.assertTrue(self._term_field_accepts(AddNewStudentRegistrationForm, self.t1))
        self.assertFalse(self._term_field_accepts(AddNewStudentRegistrationForm, self.t2))
