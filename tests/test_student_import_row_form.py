import datetime
from django.test import TestCase
from cis.models.highschool import HighSchool
from cis.forms.student_import import StudentImportRowForm


def _base_row(**over):
    row = {
        'first_name': 'ann', 'last_name': 'lee',
        'email': 'ann@example.com',
        'permanent_address_country': 'US',
        'permanent_address': '1 Main St', 'city': 'Spokane',
        'state': 'WA', 'zip_code': '99201',
        'preferred_phone': 'Mobile',
        'home_phone': '5095551234', 'cell_phone': '5095559999',
        'legal_sex': 'f',
        'date_of_birth': '05/14/2012',
        'start_date': '09/01/2026', 'graduation_date': '06/01/2028',
        'highschool_ceeb': '480123',
        'same_as_permanent': 'true',
    }
    row.update(over)
    return row


class StudentImportRowFormTests(TestCase):
    def setUp(self):
        self.hs = HighSchool.objects.create(name='Central HS', code='480123')

    def test_valid_row_resolves_ceeb_to_highschool(self):
        form = StudentImportRowForm(data=_base_row())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['highschool'], self.hs)
        self.assertEqual(form.cleaned_data['first_name'], 'Ann')  # title-cased

    def test_unknown_ceeb_is_an_error(self):
        form = StudentImportRowForm(data=_base_row(highschool_ceeb='000000'))
        self.assertFalse(form.is_valid())
        self.assertIn('highschool', form.errors)

    def test_ceeb_outside_allowed_scope_is_an_error(self):
        other = HighSchool.objects.create(name='Other HS', code='999999')
        form = StudentImportRowForm(
            data=_base_row(highschool_ceeb='999999'),
            highschools=HighSchool.objects.filter(pk=self.hs.pk),
        )
        self.assertFalse(form.is_valid())
        self.assertIn('highschool', form.errors)

    def test_existing_email_does_not_raise_here(self):
        # Duplicate classification is the importer's job, not the form's.
        from cis.models.customuser import CustomUser
        CustomUser.objects.create(username='ann@example.com', email='ann@example.com')
        form = StudentImportRowForm(data=_base_row())
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_required_field_flags_error(self):
        row = _base_row()
        del row['first_name']
        form = StudentImportRowForm(data=row)
        self.assertFalse(form.is_valid())
        self.assertIn('first_name', form.errors)


class EthnicityStorageMetadataTests(TestCase):
    """ewu#39 — the DelimitedMultipleChoiceField that replaces `ethnicity` must
    inherit the storage metadata of the field it replaces.

    MetaFormMixin._save_fields_to_models keys off `storage_target`; a
    replacement built fresh has none, so the loop skips it. The row validates,
    the import reports success, and the value is silently discarded. Nothing
    errors, so it only surfaces when someone notices the column is empty on
    records that were definitely imported with it.
    """

    def setUp(self):
        from django.contrib.auth.models import Group
        # Student.save() adds the 'student' group unconditionally.
        Group.objects.get_or_create(name='student')
        self.hs = HighSchool.objects.create(name='Central HS', code='480123')

    def test_replacement_field_keeps_its_storage_metadata(self):
        form = StudentImportRowForm(data=_base_row())
        field = form.fields['ethnicity']
        self.assertEqual(getattr(field, 'storage_target', None), 'student')
        self.assertEqual(getattr(field, 'storage_path', None), 'ethnicity')

    def test_a_valid_row_actually_persists_ethnicity(self):
        """The assertion that matters: metadata could be present and the value
        still never written."""
        from cis.models.customuser import CustomUser
        from cis.models.student import Student

        form = StudentImportRowForm(data=_base_row(ethnicity='2|5'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['ethnicity'], ['2', '5'])

        user = CustomUser.objects.create(
            username='ann@example.com', email='ann@example.com')
        student = Student.objects.create(user=user)
        form.student = student
        form.save(student=student, commit=True)

        student.refresh_from_db()
        self.assertEqual(sorted(student.ethnicity), ['2', '5'])

    def test_single_value_cell_still_persists(self):
        from cis.models.customuser import CustomUser
        from cis.models.student import Student

        form = StudentImportRowForm(data=_base_row(ethnicity='5'))
        self.assertTrue(form.is_valid(), form.errors)

        user = CustomUser.objects.create(
            username='ann2@example.com', email='ann2@example.com')
        student = Student.objects.create(user=user)
        form.student = student
        form.save(student=student, commit=True)

        student.refresh_from_db()
        self.assertEqual(list(student.ethnicity), ['5'])
