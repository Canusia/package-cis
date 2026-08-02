"""PT-20: stored XSS in student detail (asHTML|safe).

Fix = CE-only edit method + server-side sanitization of plain-text profile
fields so stored values can never contain HTML markup. Templates/|safe are
intentionally left unchanged.
"""
from django.test import TestCase

from cis.utils import sanitize_plain_text


class SanitizePlainTextTests(TestCase):
    def test_strips_img_onerror_payload(self):
        out = sanitize_plain_text('<img src=x onerror=console.log(1)>')
        self.assertNotIn('<', out)
        self.assertNotIn('>', out)
        # The dangerous tag is gone; no executable markup remains.
        self.assertNotIn('<img', out)

    def test_no_angle_brackets_survive(self):
        for payload in [
            '<script>alert(1)</script>',
            '<svg onload=alert(1)>',
            '<img src=x onerror="alert(1)"',  # malformed / unclosed
            'plain <b>bold</b> text',
        ]:
            out = sanitize_plain_text(payload)
            self.assertNotIn('<', out)
            self.assertNotIn('>', out)

    def test_preserves_ordinary_text(self):
        self.assertEqual(sanitize_plain_text('  Mary-Jane  '), 'Mary-Jane')
        self.assertEqual(sanitize_plain_text("O'Brien"), "O'Brien")

    def test_non_string_passthrough(self):
        self.assertIsNone(sanitize_plain_text(None))
        self.assertEqual(sanitize_plain_text(123), 123)


from cis.forms.student_profile import StudentCISForm, StudentProfileForm


class StudentProfileFormSanitizeTests(TestCase):
    """Every free-text field is sanitized (not just an allowlist), and the
    sanitizer is defined on the base form so all variants inherit it."""

    def test_every_text_field_is_sanitized(self):
        form = StudentCISForm()  # student=None, request=None
        form.cleaned_data = {
            'middle_name': '<img src=x onerror=alert(1)>',
            'first_name': 'Al<b>ice</b>',
            'mailing_city': 'Town<script>x</script>',
            # Fields that were NOT in the old allowlist must now be sanitized too.
            'email': 'a@b.com<script>steal()</script>',
            'secondary_email': 'x<svg onload=alert(1)>@c.com',
            'some_future_field': 'hi <iframe>',
        }
        form._sanitize_text_fields()

        for name in form.cleaned_data:
            self.assertNotIn('<', form.cleaned_data[name],
                             f'{name} still contains markup')
            self.assertNotIn('>', form.cleaned_data[name],
                             f'{name} still contains markup')

    def test_passwords_are_never_sanitized(self):
        form = StudentCISForm()
        form.cleaned_data = {
            'password': 'a<b>P@ss>1',
            'confirm_password': 'a<b>P@ss>1',
            'first_name': 'Bob<i>x</i>',
        }
        form._sanitize_text_fields()
        # Passwords are hashed, never rendered — they must persist verbatim.
        self.assertEqual(form.cleaned_data['password'], 'a<b>P@ss>1')
        self.assertEqual(form.cleaned_data['confirm_password'], 'a<b>P@ss>1')
        # ...while ordinary fields are still scrubbed.
        self.assertNotIn('<', form.cleaned_data['first_name'])

    def test_non_string_values_pass_through(self):
        form = StudentCISForm()
        sentinel = object()
        form.cleaned_data = {'date_of_birth': None, 'us_citizen': True,
                             'obj': sentinel}
        form._sanitize_text_fields()
        self.assertIsNone(form.cleaned_data['date_of_birth'])
        self.assertIs(form.cleaned_data['us_citizen'], True)
        self.assertIs(form.cleaned_data['obj'], sentinel)

    def test_sanitizer_is_inherited_from_the_shared_mixin(self):
        # Defined once on MetaFormMixin so every with_meta form gets it — the
        # profile variants and the spec-driven application form — and no
        # variant can quietly override it.
        from cis.forms.utils import MetaFormMixin

        self.assertIn('_sanitize_text_fields', MetaFormMixin.__dict__)
        self.assertNotIn('_sanitize_text_fields', StudentProfileForm.__dict__)
        self.assertNotIn('_sanitize_text_fields', StudentCISForm.__dict__)


class StudentCISFormSaveSanitizeTests(TestCase):
    """save() is the universal choke point: it runs for every variant
    (including StudentCISForm, whose _clean_form bypass skips clean())."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from cis.models import CustomUser, Student
        Group.objects.get_or_create(name='student')
        self.student = Student.objects.create(
            user=CustomUser.objects.create_user(
                email='victim@x.com', password='p', username='victim@x.com'),
        )

    def test_save_sanitizes_all_fields_before_persisting(self):
        form = StudentCISForm()
        form.cleaned_data = {
            'middle_name': '<script>alert(1)</script>',
            'first_name': 'Eve<img src=x onerror=alert(1)>',
            'password': 'k<e>ep>Me',
        }
        # save() may raise later on incomplete cleaned_data, but its FIRST
        # action is sanitization — assert cleaned_data was scrubbed regardless.
        try:
            form.save(student=self.student, commit=False)
        except Exception:
            pass
        self.assertNotIn('<', form.cleaned_data['middle_name'])
        self.assertNotIn('<', form.cleaned_data['first_name'])
        self.assertEqual(form.cleaned_data['password'], 'k<e>ep>Me')


import uuid

from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()


class StudentEditMethodAuthzTests(TestCase):
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

    @classmethod
    def setUpTestData(cls):
        for name in ('ce', 'highschool_admin'):
            Group.objects.get_or_create(name=name)

        ce = User.objects.create_user(
            username='ce_pt20', email='ce_pt20@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce

        hsa = User.objects.create_user(
            username='hsa_pt20', email='hsa_pt20@example.com', password='x',
            first_name='Hank', last_name='Admin',
        )
        hsa.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa

        cls.url = reverse('cis:add_new_ajax')
        cls.bogus_id = uuid.uuid4()

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')

    def test_hsadmin_cannot_run_student_edit(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.post(self.url, {
            'model': 'student', 'id': str(self.bogus_id),
            'middle_name': '<img src=x onerror=alert(1)>', 'ajax': '1',
        })
        self.assertEqual(resp.status_code, 403)

    def test_ce_is_admitted_to_student_edit(self):
        self.client.force_login(self.ce_user)
        resp = self.client.post(self.url, {
            'model': 'student', 'id': str(self.bogus_id), 'ajax': '1',
        })
        # Past the CE gate (not 403); 404 because the bogus student id is
        # looked up via get_object_or_404.
        self.assertNotEqual(resp.status_code, 403)
        self.assertEqual(resp.status_code, 404)
