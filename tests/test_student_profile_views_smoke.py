"""The three consumers of the profile forms each render after the relocation.

student/views/dashboard.py resolves its form by name through globals(), which
only works because the module-level import binds the lazily-resolved class —
worth an actual request rather than a unit assertion.

The classes below go one step further than the brief's Step 1 unit checks:
they drive each of the three real pages through Django's test client with an
authenticated (or, for signup, anonymous-but-valid) fixture, so the actual
view code, URL routing and template rendering run end to end rather than just
the form constructor. Browser login was not available in this environment
(see the task-6 report); these are the closest automatable substitute.
"""
from django.conf import settings as django_settings
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.http import HttpRequest
from django.test import TestCase
from django.urls import reverse

from cis.models.customuser import CustomUser
from cis.models.settings import Setting
from cis.models.student import Student
from cis.models.term import AcademicYear, Term

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None


def _registrations_key():
    """The tenant-prefixed key cis.utils.registration_terms()/
    is_student_registration_open() read. Never hardcode the literal — the
    prefix is environment-dependent (CAMPUS_CODE_PREFIX, 'TEST' under test
    settings)."""
    return getattr(django_settings, 'CAMPUS_CODE_PREFIX') + '_cis_registrations'


class ProfileFormViewSmokeTest(TestCase):

    def test_student_portal_profile_form_instantiates(self):
        from cis.forms.student_profile import StudentEditableForm
        form = StudentEditableForm(None, request=None)
        self.assertIsInstance(form.fields, dict)

    def test_ce_admin_form_instantiates_and_renders(self):
        from cis.forms.student_profile import StudentCISForm
        form = StudentCISForm(None, request=None)
        html = form.as_p()
        self.assertIn('psid', html)
        for name in form.fields.values():
            self.assertFalse(name.required)

    def test_dashboard_module_resolves_the_form_by_name(self):
        # importlib.import_module, not `import student.views.dashboard as
        # dash`: student/views/__init__.py does
        # `from .dashboard import dashboard`, which rebinds the package
        # attribute `student.views.dashboard` to the *function* of the same
        # name, shadowing the submodule. That's a pre-existing quirk of the
        # package's re-export style, unrelated to this relocation -- using
        # import_module reaches the actual module (and sys.modules entry)
        # regardless of that shadowing.
        import importlib
        dash = importlib.import_module('student.views.dashboard')
        self.assertIn('StudentEditableForm', vars(dash))

    def test_import_row_form_still_subclasses_the_tenant_base(self):
        from cis.forms.student_import import StudentImportRowForm
        from myce_tenant_configs.services.student_profile_form import (
            StudentProfileForm as TenantForm)
        self.assertTrue(issubclass(StudentImportRowForm, TenantForm))

    def test_dynamic_export_report_still_reads_the_field_set(self):
        from cis.reports import student_profile_dynamic_export  # noqa: F401

    def test_import_schema_still_reads_the_field_set(self):
        from cis.services.importers import student_import_schema  # noqa: F401


class StudentPortalProfilePageTest(TestCase):
    """/student/profile/ — student.views.dashboard.profile, which resolves
    StudentEditableForm via globals()[form_name]. Exercises the real
    verify_account_complete decorator gate plus template rendering."""

    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler blows up in tests
        # because the request has no usable IP (same pattern as
        # test_edit_student_authorization / test_bill_pay_render).
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    def setUp(self):
        Group.objects.get_or_create(name='student')

        self.user = CustomUser.objects.create_user(
            username='studprofile@example.com',
            email='studprofile@example.com',
            password='x',
            first_name='Prof',
            last_name='Ile',
        )
        # psid, so has_usable_password() + psid gate in
        # verify_account_complete both pass.
        self.user.psid = 'PSID-1'
        self.user.save()
        self.user.groups.add(Group.objects.get(name='student'))

        # ferpa_completed_for must equal the registration_terms() code list.
        # With no registration_terms configured for any Term, the empty list
        # trivially satisfies both sides of that comparison.
        self.student = Student.objects.create(user=self.user, meta={
            'ferpa_completed_for': [],
        })

        # force_login fires user_logged_in, which cis.signals.onboarding
        # .reseed_on_term_rollover handles by creating a StudentOnboarding
        # row for cis.utils.active_term(). active_term() falls back to
        # Term.objects.first() when unset, which is None with no Term in the
        # DB at all -> StudentOnboarding.term_id NOT NULL violation. A real
        # Term (referenced as active_term below) avoids that.
        academic_year = AcademicYear.objects.create(name='Smoke Test Year')
        self.term = Term.objects.create(
            academic_year=academic_year, code='SMK', label='Smoke Term')

        # registration_terms() raises AttributeError on None unless this
        # Setting row exists; an empty registration_terms list keeps the
        # queryset (and thus regis_terms) empty, matching student.meta above.
        Setting.objects.create(
            key=_registrations_key(),
            value={
                'active_term': str(self.term.id),
                'registration_terms': [],
            },
        )

        # portal_lang(request).from_db() parses the '<role>_menu' JSON blob
        # off the menu Setting; without installed defaults it's None and
        # json.loads blows up (same fixture as
        # student.tests.test_bill_pay_render.BillPayRenderTest).
        from cis.settings.menu import menu as menu_settings
        from cis.settings.student_portal import student_portal
        menu_settings(HttpRequest()).install()
        student_portal(HttpRequest()).install()

        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.user)

    def test_profile_page_renders_editable_form(self):
        resp = self.client.get(reverse('student:profile'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        # first_name is common to every derived profile form; its presence
        # confirms StudentEditableForm actually rendered fields, not just an
        # empty page.
        self.assertIn('first_name', content)

    def test_profile_page_applies_configured_weights_and_labels(self):
        """Unit tests (test_meta_form_mixin_ordering) already prove
        apply_field_weights()/_load_field_labels_from_db() work in isolation.
        What they don't prove is that the view actually constructs the form
        at request time with a real student_profile Setting in play — this
        closes that gap the same way the rest of this file does, with a real
        GET through the URL/view/decorator stack.

        first_name is declared early in StudentProfileForm and city much
        later; a weight config that inverts them is a clear, observable
        reordering in the rendered HTML.
        """
        from cis.settings.student_profile import (
            reset_profile_fields_cache, student_profile)

        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {
                'field_weights': {'city': 1, 'first_name': 100},
                'field_messages': {
                    'first_name': {'label': 'Renamed For Test'},
                },
            }},
        )
        self.addCleanup(reset_profile_fields_cache)

        resp = self.client.get(reverse('student:profile'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()

        # Order: anchor on the real input elements, not a bare field-name
        # substring, so a label or help-text mention elsewhere in the page
        # can't produce a false match.
        city_pos = content.index('name="city"')
        first_name_pos = content.index('name="first_name"')
        self.assertLess(
            city_pos, first_name_pos,
            'city (weight 1) should render before first_name (weight 100)')

        # Label: the configured override string must appear verbatim.
        self.assertIn('Renamed For Test', content)


class CEAdminStudentEditFormPageTest(TestCase):
    """/ce/add_new_ajax/?model=student — cis.views.ajax.add_new dispatches to
    cis.views.student.edit_record (aliased edit_student), which renders
    StudentCISForm (imported at cis/views/student.py:51 as StudentProfileForm).
    """

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
        Group.objects.get_or_create(name='ce')
        Group.objects.get_or_create(name='student')

        target_user = CustomUser.objects.create_user(
            username='target_ce_profile@example.com',
            email='target_ce_profile@example.com',
            password='x',
            first_name='Target',
            last_name='Student',
        )
        self.student = Student.objects.create(user=target_user)

        self.ce_user = CustomUser.objects.create_user(
            username='ce_profile_smoke@example.com',
            email='ce_profile_smoke@example.com',
            password='x',
            first_name='Cee',
            last_name='Ee',
            is_staff=True,
        )
        self.ce_user.groups.add(Group.objects.get(name='ce'))

        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.ce_user)

    def test_ce_admin_edit_form_renders(self):
        resp = self.client.get(reverse('cis:add_new_ajax'), {
            'model': 'student',
            'id': str(self.student.id),
            'ajax': '1',
        })
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('first_name', content)
        # psid is only ever populated on the CE admin variant
        # (CISProfileMixin.__init__), so its presence distinguishes this
        # form from the student-portal editable one.
        self.assertIn('psid', content)


class SignupApplicationPageTest(TestCase):
    """/student/complete_signup/<id> — student.views.onboarding.complete_signup,
    which builds the form via get_application_form(), the full
    StudentProfileForm path used by new-student signup."""

    def setUp(self):
        # Student.save() calls Group.objects.get(name='student') unconditionally.
        Group.objects.get_or_create(name='student')

        # Public view (login_required = False), but is_student_registration_open()
        # must be True to reach the form-rendering branch instead of the
        # "registration closed" template.
        Setting.objects.create(
            key=_registrations_key(),
            value={
                'starting_date': '01/01/2020',
                'ending_date': '01/01/2099',
                'registration_terms': [],
            },
        )

        unverified_user = CustomUser.objects.create_user(
            username='signup_smoke@example.com',
            email='signup_smoke@example.com',
            first_name='Sign',
            last_name='Up',
        )
        self.student = Student.objects.create(user=unverified_user, meta={})

        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')

    def test_signup_application_form_renders(self):
        resp = self.client.get(
            reverse('student:complete_signup', args=[self.student.id]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('first_name', content)
