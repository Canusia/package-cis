"""The three public names resolve through the tenant app, lazily, and the
derived classes put cis's behavior mixin ahead of the tenant field set."""
from django import forms
from django.test import TestCase
from cis.tests.tenant_support import requires_tenant_service


class StudentProfileResolutionTest(TestCase):

    @requires_tenant_service('student_profile_form')
    def test_base_form_is_the_tenant_class(self):
        from cis.forms.student_profile import StudentProfileForm
        from myce_tenant_configs.services.student_profile_form import (
            StudentProfileForm as TenantForm)
        self.assertIs(StudentProfileForm, TenantForm)

    @requires_tenant_service('student_profile_form')
    def test_derived_forms_subclass_the_tenant_base(self):
        from cis.forms.student_profile import (
            StudentCISForm, StudentEditableForm)
        from myce_tenant_configs.services.student_profile_form import (
            StudentProfileForm as TenantForm)
        self.assertTrue(issubclass(StudentEditableForm, TenantForm))
        self.assertTrue(issubclass(StudentCISForm, TenantForm))

    @requires_tenant_service('student_profile_form')
    def test_behavior_mixin_precedes_the_tenant_base_in_mro(self):
        from cis.forms.student_profile import (
            CISProfileMixin, EditableProfileMixin, StudentCISForm,
            StudentEditableForm)
        from myce_tenant_configs.services.student_profile_form import (
            StudentProfileForm as TenantForm)
        for cls, mixin in ((StudentEditableForm, EditableProfileMixin),
                           (StudentCISForm, CISProfileMixin)):
            mro = cls.__mro__
            self.assertLess(mro.index(mixin), mro.index(TenantForm))

    def test_derived_classes_are_cached(self):
        # isinstance checks across a request and Django's form-media caching
        # both assume a stable class object.
        import cis.forms.student_profile as mod
        self.assertIs(mod.StudentEditableForm, mod.StudentEditableForm)
        self.assertIs(mod.StudentCISForm, mod.StudentCISForm)

    def test_ce_form_actually_collects_the_admin_fields(self):
        # Guards the DeclarativeFieldsMetaclass trap: Field instances on a
        # plain mixin are dropped silently, with no error to notice.
        from cis.forms.student_profile import StudentCISForm
        for name in ('psid', 'alt_username', 'secondary_email', 'id'):
            self.assertIn(name, StudentCISForm.base_fields, name)

    def test_derived_names_report_themselves_correctly(self):
        from cis.forms.student_profile import StudentCISForm, StudentEditableForm
        self.assertEqual(StudentEditableForm.__name__, 'StudentEditableForm')
        self.assertEqual(StudentCISForm.__name__, 'StudentCISForm')

    def test_unknown_attribute_still_raises_attribute_error(self):
        import cis.forms.student_profile as mod
        with self.assertRaises(AttributeError):
            mod.NoSuchForm

    def test_editable_fields_default_is_fail_safe_when_tenant_omits_it(self):
        from unittest.mock import patch
        import cis.forms.student_profile as mod

        class _Bare:
            pass

        with patch.object(mod, '_tenant_module', return_value=_Bare()):
            self.assertEqual(mod.tenant_editable_fields(), ())

    def test_ce_hidden_fields_default_is_empty_when_tenant_omits_it(self):
        """Absent export -> (), i.e. today's behaviour. Unlike EDITABLE_FIELDS
        the safe default here is 'hide nothing extra': cis already drops the
        generic three, and defaulting to anything more would silently remove
        fields a tenant does collect."""
        from unittest.mock import patch
        import cis.forms.student_profile as mod

        class _Bare:
            pass

        with patch.object(mod, '_tenant_module', return_value=_Bare()):
            self.assertEqual(mod.tenant_ce_hidden_fields(), ())

    def test_ce_hidden_fields_reads_the_tenant_export_as_a_tuple(self):
        from unittest.mock import patch
        import cis.forms.student_profile as mod

        class _Tenant:
            CE_HIDDEN_FIELDS = ['no_ssn', 'agree_tuition_responsibility']

        with patch.object(mod, '_tenant_module', return_value=_Tenant()):
            hidden = mod.tenant_ce_hidden_fields()
        # A tuple, so a caller cannot mutate the tenant's default in place.
        self.assertEqual(hidden, ('no_ssn', 'agree_tuition_responsibility'))
        self.assertIsInstance(hidden, tuple)

    def test_ce_form_drops_the_tenant_hidden_fields(self):
        """The seam's whole point: a CE staffer entering a record on a
        student's behalf must not fill in fields only the student can answer
        (an SSN opt-out, an agreement checkbox)."""
        from unittest.mock import patch
        import cis.forms.student_profile as mod

        target = next(n for n in ('gender', 'legal_sex', 'ethnicity')
                      if n in mod.StudentCISForm.base_fields)

        with patch.object(mod, 'tenant_ce_hidden_fields',
                          return_value=(target,)):
            form = mod.StudentCISForm(None, request=None)
        self.assertNotIn(target, form.fields)

        # ...and the generic three still go regardless.
        for name in ('verify_student_ssn', 'password', 'confirm_password'):
            self.assertNotIn(name, form.fields)

    def test_ce_form_keeps_every_field_when_the_tenant_hides_nothing(self):
        from unittest.mock import patch
        import cis.forms.student_profile as mod

        with patch.object(mod, 'tenant_ce_hidden_fields', return_value=()):
            form = mod.StudentCISForm(None, request=None)
        for name in ('psid', 'first_name'):
            self.assertIn(name, form.fields)

    def test_ce_hidden_fields_naming_an_absent_field_is_harmless(self):
        """Tenants drift; a stale name in CE_HIDDEN_FIELDS must not 500 the CE
        student form."""
        from unittest.mock import patch
        import cis.forms.student_profile as mod

        with patch.object(mod, 'tenant_ce_hidden_fields',
                          return_value=('not_a_real_field',)):
            form = mod.StudentCISForm(None, request=None)
        self.assertIn('psid', form.fields)

    def test_importing_the_module_does_not_resolve_the_tenant_app(self):
        # Lazy is a hard requirement: the tenant module imports cis.models at
        # module level, so eager resolution risks AppRegistryNotReady. Execute a
        # fresh module object that is never registered in sys.modules — an
        # importlib.import_module here would rebind both sys.modules AND the
        # cis.forms package attribute, leaving a mock-bound module resident and
        # breaking later tests with a misleading metaclass conflict.
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.find_spec('cis.forms.student_profile')
        fresh = importlib.util.module_from_spec(spec)
        with patch('cis.services.tenant_services.get_tenant_service') as spy:
            spec.loader.exec_module(fresh)
            spy.assert_not_called()
