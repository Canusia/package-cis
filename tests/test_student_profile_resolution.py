"""The three public names resolve through the tenant app, lazily, and the
derived classes put cis's behavior mixin ahead of the tenant field set."""
from django import forms
from django.test import TestCase


class StudentProfileResolutionTest(TestCase):

    def test_base_form_is_the_tenant_class(self):
        from cis.forms.student_profile import StudentProfileForm
        from myce_tenant_configs.services.student_profile_form import (
            StudentProfileForm as TenantForm)
        self.assertIs(StudentProfileForm, TenantForm)

    def test_derived_forms_subclass_the_tenant_base(self):
        from cis.forms.student_profile import (
            StudentCISForm, StudentEditableForm)
        from myce_tenant_configs.services.student_profile_form import (
            StudentProfileForm as TenantForm)
        self.assertTrue(issubclass(StudentEditableForm, TenantForm))
        self.assertTrue(issubclass(StudentCISForm, TenantForm))

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
