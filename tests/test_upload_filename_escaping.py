"""Uploaded filenames and descriptions must not execute in the CE's page.

Both tuition-assistance forms build an "Uploaded Files" table by string
concatenation and hand the result to mark_safe(), which asserts the escaping
has already happened. It had not. Three of the interpolated values are
attacker-controlled: the filename and the description come straight from what
the uploader supplied, and the URL is derived from the stored name.

The uploader is a student; the page that renders this is the CE admin's. So a
crafted filename runs in the admin's session, not the uploader's.
"""
import uuid
from unittest import mock

from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models.customuser import CustomUser
from cis.models.student import (
    Student,
    StudentTuitionAssistance,
    StudentTuitionAssistanceDocument,
)
from cis.models.term import AcademicYear, Term

# Slash-free on purpose: `filename` is os.path.basename(media.name), so a
# payload containing "/" is truncated at it. That is not a defence -- an
# onerror handler needs no slashes.
SCRIPT_IN_FILENAME = '<img src=x onerror=alert(1)>.pdf'
SCRIPT_IN_DESCRIPTION = '<script>alert(2)</script>'


def _sfx():
    return uuid.uuid4().hex[:8]


class _HostileUploadMixin:
    """A tuition-assistance record carrying one hostile document.

    `media` is assigned as a bare string so no file is written -- this
    container has no S3 bucket. `url` is patched for the same reason.
    """

    @classmethod
    def setUpTestData(cls):
        # Student.save() assigns this group and raises if it is absent.
        Group.objects.get_or_create(name='student')

        email = f'{_sfx()}@example.com'
        user = CustomUser.objects.create_user(
            username=email, email=email, password='x')
        cls.student = Student.objects.create(user=user)

        academic_year = AcademicYear.objects.create(name=f'AY{_sfx()}')
        cls.term = Term.objects.create(
            academic_year=academic_year, code=f'T{_sfx()}', label=f'L{_sfx()}')

        cls.faa = StudentTuitionAssistance.objects.create(
            student=cls.student, term=cls.term)
        StudentTuitionAssistanceDocument.objects.create(
            tuition_assistance=cls.faa,
            media=SCRIPT_IN_FILENAME,
            description=SCRIPT_IN_DESCRIPTION,
        )

    def setUp(self):
        patcher = mock.patch(
            'cis.storage_backend.PrivateMediaStorage.url',
            return_value='https://example.test/signed.pdf')
        patcher.start()
        self.addCleanup(patcher.stop)

    def assertEscaped(self, help_text, raw):
        rendered = str(help_text)
        self.assertNotIn(raw, rendered)
        self.assertIn(raw.replace('<', '&lt;').replace('>', '&gt;'), rendered)


class ManageFAAFormEscapingTests(_HostileUploadMixin, TestCase):

    def _help_text(self):
        from cis.forms.student import ManageFAAForm
        return ManageFAAForm(self.faa).fields['file'].help_text

    def test_filename_is_escaped(self):
        self.assertEscaped(self._help_text(), SCRIPT_IN_FILENAME)

    def test_table_markup_still_renders(self):
        """The fix must escape the interpolations, not the whole blob."""
        rendered = str(self._help_text())
        self.assertIn('<table class="table table-striped">', rendered)
        self.assertIn('Uploaded Files', rendered)


class StudentTuitionAssistanceFormEscapingTests(_HostileUploadMixin, TestCase):

    def _help_text(self):
        from cis.forms.student import StudentTuitionAssistanceForm
        return StudentTuitionAssistanceForm(
            self.student, self.term, faa=self.faa).fields['file'].help_text

    def test_filename_is_escaped(self):
        self.assertEscaped(self._help_text(), SCRIPT_IN_FILENAME)

    def test_description_is_escaped(self):
        """Only this form renders the description -- and it was unescaped too,
        which the issue did not mention."""
        self.assertEscaped(self._help_text(), SCRIPT_IN_DESCRIPTION)

    def test_table_markup_still_renders(self):
        rendered = str(self._help_text())
        self.assertIn('<table class="table table-striped">', rendered)
        self.assertIn('Uploaded Files', rendered)
