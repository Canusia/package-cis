"""The edit_registration tab resolves EditStudentRegistration through the
tenant-service indirection. Guards that the tab callable resolves the moved form
rather than importing it statically from cis.forms.section.
"""
import inspect

from django.test import TestCase

import cis.tabs.registration as regtabs


class EditRegistrationTabResolutionTests(TestCase):
    def test_tab_source_uses_tenant_service_resolver(self):
        src = inspect.getsource(regtabs.edit_registration_tab)
        self.assertIn("get_tenant_service('registration_form')", src,
                      msg='tab should resolve the form via get_tenant_service')

    def test_tab_does_not_static_import_form_from_cis_forms(self):
        src = inspect.getsource(regtabs.edit_registration_tab)
        self.assertNotIn('from cis.forms.section import EditStudentRegistration', src,
                         msg='tab should not statically import the moved form')
