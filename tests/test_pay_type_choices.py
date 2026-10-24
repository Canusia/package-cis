"""Pay-type choices are tenant-overridable (#89): StudentRegistration.pay_type
and HighSchool.hs_pay_type resolve through cis.services.pay_types, the
package lists stay the default, and relabeling needs no migration."""
from unittest import mock

from django.test import SimpleTestCase

from cis.models.highschool import HighSchool
from cis.models.section import StudentRegistration
from cis.services import pay_types

STATE = [('', '---'), ('student', 'Student Pay'), ('state', 'State Funds')]
HS_STATE = [('Student Pay', 'Student'), ('State Funds', 'State Funds')]


def _override(module, attr):
    assert module == 'pay_types'
    return {'REGISTRATION_PAY_TYPES': STATE, 'HIGHSCHOOL_PAY_TYPES': HS_STATE}.get(attr)


class PayTypeChoicesTests(SimpleTestCase):
    def test_package_defaults(self):
        with mock.patch.object(pay_types, 'get_tenant_override', lambda m, a: None):
            self.assertEqual(StudentRegistration.PAY_OPTIONS,
                             pay_types.DEFAULT_REGISTRATION_PAY_TYPES)
            self.assertEqual(HighSchool.PAY_TYPE_OPTIONS,
                             pay_types.DEFAULT_HIGHSCHOOL_PAY_TYPES)

    def test_tenant_lists_replace_the_defaults(self):
        with mock.patch.object(pay_types, 'get_tenant_override', _override):
            self.assertEqual(StudentRegistration.PAY_OPTIONS, STATE)
            self.assertEqual(
                list(StudentRegistration._meta.get_field('pay_type').choices), STATE)
            self.assertEqual(
                list(HighSchool._meta.get_field('hs_pay_type').choices), HS_STATE)
            reg = StudentRegistration(pay_type='state')
            self.assertEqual(reg.get_pay_type_display(), 'State Funds')
            self.assertEqual(reg.pay_type_pretty, 'State Funds')

    def test_fields_keep_the_callable_for_migrations(self):
        field = StudentRegistration._meta.get_field('pay_type')
        self.assertIs(field.deconstruct()[3]['choices'],
                      pay_types.registration_pay_type_choices)
