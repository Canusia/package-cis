"""package-cis#57 — the tenant StudentProfileForm is bound per call, so
`override_settings(TENANT_SERVICES_APP=...)` reaches the importer, the import
row form, the derived profile forms and the dynamic export.

Before this, three places bound the tenant form once per process: the import
schema imported it at module load, StudentImportRowForm subclassed it at module
load, and `_class_cache` was keyed by class name only — so a test pointed at
`cis.tests.fake_tenant` silently got the host tenant's fields.
"""
from django.test import TestCase, override_settings

import cis.forms.student_profile as profile_mod
from cis.services.importers.student_import_schema import StudentImportColumns

FAKE_TENANT = 'cis.tests.fake_tenant'


def _fake_form():
    from cis.tests.fake_tenant.services.student_profile_form import StudentProfileForm
    return StudentProfileForm


class TenantBindingTests(TestCase):

    def test_import_schema_reads_the_current_tenant_form(self):
        with override_settings(TENANT_SERVICES_APP=FAKE_TENANT):
            headers = StudentImportColumns.headers()
            required = StudentImportColumns.required()
        self.assertIn('fake_color', headers)
        self.assertIn('fake_meta_note', headers)
        self.assertIn('fake_color', required)
        self.assertNotIn('fake_meta_note', required)
        # hidden, non-importable and mechanic fields never become columns
        for name in ('fake_hidden_code', 'fake_attestation', 'password',
                     'signature', 'highschool'):
            self.assertNotIn(name, headers)
        self.assertIn(StudentImportColumns.CEEB_COLUMN, headers)

    def test_schema_form_class_follows_the_setting(self):
        with override_settings(TENANT_SERVICES_APP=FAKE_TENANT):
            self.assertIs(StudentImportColumns._form_class(), _fake_form())
        self.assertIsNot(StudentImportColumns._form_class(), _fake_form())

    def test_row_form_is_built_on_the_current_tenant_form(self):
        from cis.forms import student_import
        with override_settings(TENANT_SERVICES_APP=FAKE_TENANT):
            cls = student_import.student_import_row_form()
            self.assertTrue(issubclass(cls, _fake_form()))
            # stable per tenant: isinstance checks and media caching rely on it
            self.assertIs(cls, student_import.student_import_row_form())
            self.assertIs(cls, student_import.StudentImportRowForm)
        self.assertFalse(issubclass(student_import.student_import_row_form(),
                                    _fake_form()))

    def test_legacy_from_import_still_works(self):
        from cis.forms.student_import import StudentImportRowForm
        self.assertTrue(hasattr(StudentImportRowForm, 'column_notes'))
        self.assertTrue(issubclass(StudentImportRowForm,
                                   profile_mod.StudentProfileForm))

    def test_derived_profile_forms_are_cached_per_tenant(self):
        host_cis = profile_mod.StudentCISForm
        host_editable = profile_mod.StudentEditableForm
        with override_settings(TENANT_SERVICES_APP=FAKE_TENANT):
            fake_cis = profile_mod.StudentCISForm
            fake_editable = profile_mod.StudentEditableForm
            self.assertIs(fake_cis, profile_mod.StudentCISForm)
        self.assertIsNot(fake_cis, host_cis)
        self.assertIsNot(fake_editable, host_editable)
        self.assertTrue(issubclass(fake_cis, _fake_form()))
        self.assertTrue(issubclass(fake_editable, _fake_form()))
        self.assertIs(profile_mod.StudentCISForm, host_cis)

    def test_profile_fields_vocabulary_follows_the_setting(self):
        from cis.settings.student_profile import profile_fields
        host = profile_fields()
        with override_settings(TENANT_SERVICES_APP=FAKE_TENANT):
            fake = profile_fields()
        self.assertIn('fake_color', fake)
        self.assertNotIn('password', fake)
        self.assertNotIn('fake_color', host)

    def test_dynamic_export_reads_the_current_tenant_form(self):
        from cis.reports.student_profile_dynamic_export import (
            student_profile_dynamic_export)
        with override_settings(TENANT_SERVICES_APP=FAKE_TENANT):
            exported = {f['name'] for f in
                        student_profile_dynamic_export()._form_fields_for_export()}
        self.assertIn('fake_meta_note', exported)


@override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
class FakeTenantCEFormTests(TestCase):
    """CISProfileMixin against the fake tenant: the extra admin field is mixed
    in, CE_HIDDEN_FIELDS are dropped, every field is optional."""

    def test_ce_form_shape(self):
        form = profile_mod.StudentCISForm(student=None, request=None)
        self.assertIn('psid', form.fields)
        self.assertIn('id', form.fields)
        self.assertNotIn('fake_attestation', form.fields)
        self.assertNotIn('verify_student_ssn', form.fields)
        self.assertFalse(any(f.required for f in form.fields.values()))
