"""StudentImportRowForm against cis.tests.fake_tenant (package-cis#57).

Tenant-agnostic: the fields asserted are the fake tenant's, so the suite holds
on every tenant that adopts the package.
"""
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.student import Student

FAKE_TENANT = 'cis.tests.fake_tenant'


def _row_form(*args, **kwargs):
    from cis.forms.student_import import student_import_row_form
    return student_import_row_form()(*args, **kwargs)


def _base_row(**over):
    row = {
        'first_name': 'Ann', 'last_name': 'Lee',
        'email': 'Ann@Example.com',
        'date_of_birth': '05/14/2012',
        'fake_color': 'red',
        'fake_meta_note': 'hello',
        'highschool_ceeb': '480123',
    }
    row.update(over)
    return row


@override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
class StudentImportRowFormTests(TestCase):
    def setUp(self):
        self.hs = HighSchool.objects.create(name='Central HS', code='480123')

    def test_valid_row_resolves_ceeb_to_highschool(self):
        form = _row_form(data=_base_row())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['highschool'], self.hs)
        self.assertEqual(form.cleaned_data['email'], 'ann@example.com')
        self.assertEqual(form.cleaned_data['fake_color'], 'red')

    def test_unknown_ceeb_is_an_error(self):
        form = _row_form(data=_base_row(highschool_ceeb='000000'))
        self.assertFalse(form.is_valid())
        self.assertIn('highschool', form.errors)

    def test_ceeb_outside_allowed_scope_is_an_error(self):
        HighSchool.objects.create(name='Other HS', code='999999')
        form = _row_form(
            data=_base_row(highschool_ceeb='999999'),
            highschools=HighSchool.objects.filter(pk=self.hs.pk),
        )
        self.assertFalse(form.is_valid())
        self.assertIn('highschool', form.errors)

    def test_existing_email_does_not_raise_here(self):
        # Duplicate classification is the importer's job, not the form's —
        # even though the tenant form's own clean_email would reject it.
        CustomUser.objects.create(username='ann@example.com', email='ann@example.com')
        form = _row_form(data=_base_row())
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_tenant_required_field_flags_error(self):
        row = _base_row()
        del row['fake_color']
        form = _row_form(data=row)
        self.assertFalse(form.is_valid())
        self.assertIn('fake_color', form.errors)

    def test_optional_tenant_field_may_be_blank(self):
        form = _row_form(data=_base_row(fake_meta_note=''))
        self.assertTrue(form.is_valid(), form.errors)

    def test_tenant_cross_field_rule_still_runs(self):
        form = _row_form(data=_base_row(fake_color='other'))
        self.assertFalse(form.is_valid())
        self.assertIn('fake_other_color', form.errors)
        form = _row_form(data=_base_row(fake_color='other',
                                        fake_other_color='teal'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_choice_cell_matches_on_label(self):
        form = _row_form(data=_base_row(fake_color='GREEN'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['fake_color'], 'green')

    def test_non_importable_and_mechanic_fields_are_dropped(self):
        names = set(_row_form().fields)
        for name in ('fake_attestation', 'password', 'confirm_password',
                     'verify_student_ssn', 'signature'):
            self.assertNotIn(name, names)
        self.assertIn('fake_meta_note', names)


@override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
class RowFormPersistenceTests(TestCase):
    """ewu#39 — the DelimitedMultipleChoiceField that replaces `ethnicity` must
    inherit the storage metadata of the field it replaces.

    MetaFormMixin._save_fields_to_models keys off `storage_target`; a
    replacement built fresh has none, so the loop skips it. The row validates,
    the import reports success, and the value is silently discarded.
    """

    def setUp(self):
        # Student.save() adds the 'student' group unconditionally.
        Group.objects.get_or_create(name='student')
        self.hs = HighSchool.objects.create(name='Central HS', code='480123')

    def _save(self, form, email):
        user = CustomUser.objects.create(username=email, email=email)
        student = Student.objects.create(user=user)
        form.student = student
        form.save(student=student, commit=True)
        student.refresh_from_db()
        return student

    def test_replacement_field_keeps_its_storage_metadata(self):
        field = _row_form(data=_base_row()).fields['ethnicity']
        self.assertEqual(getattr(field, 'storage_target', None), 'student')
        self.assertEqual(getattr(field, 'storage_path', None), 'ethnicity')

    def test_a_valid_row_actually_persists_ethnicity(self):
        form = _row_form(data=_base_row(ethnicity='2|5'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['ethnicity'], ['2', '5'])
        student = self._save(form, 'ann@example.com')
        self.assertEqual(sorted(student.ethnicity), ['2', '5'])

    def test_single_value_cell_still_persists(self):
        form = _row_form(data=_base_row(ethnicity='5'))
        self.assertTrue(form.is_valid(), form.errors)
        student = self._save(form, 'ann2@example.com')
        self.assertEqual(list(student.ethnicity), ['5'])

    def test_meta_targets_persist(self):
        form = _row_form(data=_base_row(fake_meta_note='<b>bold</b> note'))
        self.assertTrue(form.is_valid(), form.errors)
        student = self._save(form, 'ann3@example.com')
        self.assertEqual(student.meta.get('fake_color'), 'red')
        # PT-20: markup is stripped on the way in
        self.assertNotIn('<b>', student.meta.get('fake_meta_note'))
        self.assertIn('note', student.meta.get('fake_meta_note'))
