"""Registration status labels are tenant-overridable (#90): values stay the
package's, a tenant's LABELS relabels some of them, and the pre-0071 keys
drop / wd still reach dropped / withdrawn."""
from unittest import mock

from django.test import SimpleTestCase

from cis.models.section import StudentRegistration
from cis.services import registration_statuses


class RegistrationStatusLabelTests(SimpleTestCase):
    def _with(self, labels):
        return mock.patch.object(
            registration_statuses, 'get_tenant_override',
            lambda m, a: labels if (m, a) == ('registration_statuses', 'LABELS') else None)

    def test_package_labels_by_default(self):
        with self._with(None):
            self.assertEqual(tuple(StudentRegistration.STATUS_OPTIONS),
                             registration_statuses.DEFAULT_REGISTRATION_STATUSES)

    def test_tenant_relabels_without_changing_values(self):
        with self._with({'approved': 'Ready for College Review'}):
            options = dict(StudentRegistration.STATUS_OPTIONS)
            self.assertEqual(options['approved'], 'Ready for College Review')
            self.assertEqual(options['applied'], 'Requested')
            self.assertEqual(
                [v for v, _ in StudentRegistration.STATUS_OPTIONS],
                [v for v, _ in registration_statuses.DEFAULT_REGISTRATION_STATUSES])
            self.assertEqual(
                StudentRegistration(status='approved').get_status_display(),
                'Ready for College Review')

    def test_unknown_values_are_not_added(self):
        with self._with({'mystery': 'Mystery'}):
            self.assertNotIn('mystery', dict(StudentRegistration.STATUS_OPTIONS))

    def test_pre_rename_keys_still_apply(self):
        with self._with({'drop': 'Dropped (HS)', 'wd': 'Withdrew'}):
            options = dict(StudentRegistration.STATUS_OPTIONS)
            self.assertEqual(options['dropped'], 'Dropped (HS)')
            self.assertEqual(options['withdrawn'], 'Withdrew')
