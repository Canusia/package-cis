"""PT-27: stored XSS in the administrator-position assignment flow.

Payload enters via the `new_administrator_first_name` /
`new_administrator_last_name` fields of HSAdministratorPositionForm
(POST /highschool_admin/api/admin-positions/assign), is stored on the
CustomUser, and is later rendered into the Personnel DataTable without
escaping. Fix = server-side sanitization of those two name fields so the
stored value can never contain HTML markup. Per the house decision, the
unescaped/|safe rendering sink is intentionally left unchanged.

The sanitizer helper lives in the future_sections submodule (shared with the
PT-24 plan) so the pip-installable package stays self-contained.
"""
import importlib.util

from django.test import TestCase

# future_sections may be an in-tree editable submodule (nested) or a flat pip
# install; cis ships this suite to both, so resolve the path rather than
# assuming the nested layout the host repos happen to use.
if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.utils import sanitize_plain_text
else:  # pragma: no cover
    from future_sections.utils import sanitize_plain_text


class SanitizePlainTextTests(TestCase):
    def test_strips_img_onerror_payload(self):
        out = sanitize_plain_text('<img src=x onerror=console.log(424211958)>')
        self.assertNotIn('<', out)
        self.assertNotIn('>', out)
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


from django.test import RequestFactory

from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import HSPosition

if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.forms import HSAdministratorPositionForm
else:  # pragma: no cover
    from future_sections.forms import HSAdministratorPositionForm


class HSAdministratorPositionFormSanitizeTests(TestCase):
    """The two free-text name fields must be HTML-stripped during validation,
    so the value persisted on CustomUser (and later rendered unescaped in the
    Personnel DataTable) can never contain markup. Email/FK/choice fields are
    left untouched."""

    @classmethod
    def setUpTestData(cls):
        cls.highschool = HighSchool.objects.create(name='Test HS')
        cls.position = HSPosition.objects.create(name='Principal')

    def _bound_form(self, first_name, last_name, email='poc@example.com'):
        request = RequestFactory().post('/highschool_admin/api/admin-positions/assign/')
        data = {
            'highschool': str(self.highschool.id),
            'position': str(self.position.id),
            'administrator': '',
            'administrator_not_listed': 'administrator_not_listed',
            'new_administrator_first_name': first_name,
            'new_administrator_last_name': last_name,
            'new_administrator_email': email,
            'action': 'edit_highschool_admin_role',
            'confirm_school_personnel': 'on',
        }
        return HSAdministratorPositionForm(
            request, str(self.highschool.id), str(self.position.id), data=data
        )

    def test_first_name_payload_stripped(self):
        form = self._bound_form(
            first_name='<img src=x onerror="console.log(424211958)">',
            last_name='Poc',
        )
        self.assertTrue(form.is_valid(), form.errors.as_json())
        cleaned = form.cleaned_data['new_administrator_first_name']
        self.assertNotIn('<', cleaned)
        self.assertNotIn('>', cleaned)
        self.assertNotIn('onerror', cleaned.lower())

    def test_last_name_payload_stripped(self):
        form = self._bound_form(
            first_name='Pat',
            last_name='<script>alert(1)</script>',
        )
        self.assertTrue(form.is_valid(), form.errors.as_json())
        cleaned = form.cleaned_data['new_administrator_last_name']
        self.assertNotIn('<', cleaned)
        self.assertNotIn('>', cleaned)

    def test_ordinary_names_preserved(self):
        form = self._bound_form(first_name='Mary-Jane', last_name="O'Brien")
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertEqual(form.cleaned_data['new_administrator_first_name'], 'Mary-Jane')
        self.assertEqual(form.cleaned_data['new_administrator_last_name'], "O'Brien")

    def test_email_field_not_altered(self):
        form = self._bound_form(
            first_name='Pat', last_name='Poc', email='poc@example.com',
        )
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertEqual(form.cleaned_data['new_administrator_email'], 'poc@example.com')
