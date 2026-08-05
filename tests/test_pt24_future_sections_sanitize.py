"""PT-24 — Stored XSS in Future Sections teacher_name rendering.

Remediation is INPUT SANITIZATION at the data layer: the free-text name
fields submitted through the Add-New-Teacher flow must have all HTML/angle
brackets stripped before they are persisted (and later echoed unescaped as
`teacher_name` by the course-requests API). Templates / |safe / the JS
renderer are intentionally left unchanged per house decision.
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
        out = sanitize_plain_text('<img src=x onerror=alert(1)>')
        self.assertNotIn('<', out)
        self.assertNotIn('>', out)

    def test_strips_script_tag_and_contents_markup(self):
        out = sanitize_plain_text('<script>alert(1)</script>')
        self.assertNotIn('<', out)
        self.assertNotIn('>', out)

    def test_strips_residual_angle_brackets_from_malformed_input(self):
        # strip_tags can leave residual angle brackets on malformed input;
        # the _ANGLE scrub must remove them.
        out = sanitize_plain_text('a < b > c <broken')
        self.assertNotIn('<', out)
        self.assertNotIn('>', out)

    def test_preserves_ordinary_name(self):
        self.assertEqual(sanitize_plain_text('Jane Doe'), 'Jane Doe')

    def test_preserves_hyphen_apostrophe_names(self):
        self.assertEqual(sanitize_plain_text("O'Brien-Smith"), "O'Brien-Smith")

    def test_trims_surrounding_whitespace(self):
        self.assertEqual(sanitize_plain_text('  Jane  '), 'Jane')

    def test_non_string_passthrough(self):
        self.assertIsNone(sanitize_plain_text(None))
        self.assertEqual(sanitize_plain_text(5), 5)


if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.forms import AddNewTeacherForm
else:  # pragma: no cover
    from future_sections.forms import AddNewTeacherForm


class AddNewTeacherFormSanitizeTests(TestCase):
    """The free-text name fields called out in PT-24 must be sanitized by the
    form's clean hooks before they reach Teacher.get_or_add / are stored."""

    def _form_with_cleaned(self, cleaned):
        # Bypass __init__ (which needs a live request) — we only exercise the
        # field-level clean_<name> hooks, which read self.cleaned_data.
        form = AddNewTeacherForm.__new__(AddNewTeacherForm)
        form.cleaned_data = cleaned
        return form

    def test_clean_teacher_first_name_strips_payload(self):
        form = self._form_with_cleaned(
            {'teacher_first_name': '<img src=x onerror=alert(1)>'})
        out = form.clean_teacher_first_name()
        self.assertNotIn('<', out)
        self.assertNotIn('>', out)

    def test_clean_teacher_last_name_strips_payload(self):
        form = self._form_with_cleaned(
            {'teacher_last_name': '<script>alert(1)</script>'})
        out = form.clean_teacher_last_name()
        self.assertNotIn('<', out)
        self.assertNotIn('>', out)

    def test_clean_teacher_first_name_preserves_ordinary(self):
        form = self._form_with_cleaned({'teacher_first_name': 'Jane'})
        self.assertEqual(form.clean_teacher_first_name(), 'Jane')

    def test_clean_teacher_last_name_preserves_ordinary(self):
        form = self._form_with_cleaned({'teacher_last_name': "O'Brien"})
        self.assertEqual(form.clean_teacher_last_name(), "O'Brien")

    def test_clean_teacher_first_name_handles_missing(self):
        form = self._form_with_cleaned({})
        self.assertIn(form.clean_teacher_first_name(), ('', None))

    def test_clean_highschool_course_name_strips_payload(self):
        form = self._form_with_cleaned(
            {'highschool_course_name': '<img src=x onerror=alert(1)>'})
        out = form.clean_highschool_course_name()
        self.assertNotIn('<', out)
        self.assertNotIn('>', out)

    def test_clean_highschool_course_name_preserves_ordinary(self):
        form = self._form_with_cleaned(
            {'highschool_course_name': 'AP English 101'})
        self.assertEqual(
            form.clean_highschool_course_name(), 'AP English 101')

    def test_clean_new_teacher_name_strips_payload(self):
        form = self._form_with_cleaned(
            {'new_teacher_name': '<svg onload=alert(1)>'})
        out = form.clean_new_teacher_name()
        self.assertNotIn('<', out)
        self.assertNotIn('>', out)

    def test_clean_new_teacher_name_preserves_ordinary(self):
        form = self._form_with_cleaned({'new_teacher_name': 'Jane Doe'})
        self.assertEqual(form.clean_new_teacher_name(), 'Jane Doe')


from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate


class StoredTeacherNameSanitizedTests(TestCase):
    """PT-24 outcome: the value rendered as `teacher_name`
    (str(teacher) == "last, first") must contain no markup after a new
    teacher is created through the sanitized clean hooks."""

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
        Group.objects.get_or_create(name='instructor')

    def test_created_teacher_str_has_no_markup(self):
        first = AddNewTeacherForm.__new__(AddNewTeacherForm)
        first.cleaned_data = {'teacher_first_name': '<img src=x onerror=alert(1)>'}
        clean_first = first.clean_teacher_first_name()

        last = AddNewTeacherForm.__new__(AddNewTeacherForm)
        last.cleaned_data = {'teacher_last_name': '<script>alert(1)</script>'}
        clean_last = last.clean_teacher_last_name()

        teacher = Teacher.get_or_add(
            psid=None,
            email='pt24victim@example.com',
            username='pt24victim@example.com',
            first_name=clean_first,
            last_name=clean_last,
        )
        self.assertIsNotNone(teacher)

        rendered = str(teacher)  # mirrors api.py: 'teacher_name': str(teacher)
        self.assertNotIn('<', rendered)
        self.assertNotIn('>', rendered)
