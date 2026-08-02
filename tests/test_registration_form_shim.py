"""Back-compat: cis.forms.section.EditStudentRegistration must still resolve
(the pip-installed drop_wd package imports and subclasses it). The real class
now lives in the tenant app; this shim re-exports it via get_tenant_service.
"""
from django.test import TestCase

from cis.services.tenant_services import get_tenant_service


class EditRegistrationShimTests(TestCase):
    def test_shim_resolves_to_tenant_service_class(self):
        from cis.forms.section import EditStudentRegistration as ShimClass
        tenant_class = get_tenant_service('registration_form').EditStudentRegistration
        self.assertIs(ShimClass, tenant_class)

    def test_shim_is_a_form_subclass(self):
        from django import forms
        from cis.forms.section import EditStudentRegistration
        self.assertTrue(issubclass(EditStudentRegistration, forms.Form))

    def test_unknown_attribute_still_raises_attribute_error(self):
        import cis.forms.section as section_forms
        with self.assertRaises(AttributeError):
            section_forms.ThisDoesNotExist
