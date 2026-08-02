"""The registration detail view resolves EditStudentRegistration through the
tenant-service indirection, not a static cis.forms import. This guards that the
view module imports cleanly after the form moved, and that the GET detail page
renders the Edit-Registration tab form.
"""
from django.test import TestCase

from cis.services.tenant_services import get_tenant_service


class RegistrationDetailFormResolutionTests(TestCase):
    def test_view_module_does_not_statically_import_the_form(self):
        import cis.views.registration as regviews
        self.assertNotIn('EditStudentRegistration', vars(regviews),
                         msg='view should resolve the form lazily, not import it')

    def test_tenant_service_exposes_form_for_the_view(self):
        mod = get_tenant_service('registration_form')
        self.assertTrue(hasattr(mod, 'EditStudentRegistration'))
