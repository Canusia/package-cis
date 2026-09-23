"""Regression tests for issue #19: Setting.install_defaults() must never
clobber a tenant's customised value.

The old install() pattern (try/except Setting.DoesNotExist, then an
unconditional `setting.value = defaults; setting.save()`) overwrote a
tenant's customisation every time `register_settings` ran. install_defaults()
replaces that tail: create if missing, otherwise merge in only the keys the
stored value does not already have.
"""
from unittest import mock

from django.test import TestCase, RequestFactory

from cis.models.settings import Setting
from cis.settings.access_request import access_request
from cis.settings.ferpa import ferpa


class SettingInstallDefaultsTests(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = RequestFactory()

    def test_creating_absent_setting_gets_full_defaults(self):
        key = 'test.install_defaults.creating'
        self.assertFalse(Setting.objects.filter(key=key).exists())

        defaults = {'a': '1', 'b': '2'}
        Setting.install_defaults(key, defaults)

        setting = Setting.objects.get(key=key)
        self.assertEqual(setting.value, defaults)

    def test_preserving_customised_value_survives_install_defaults(self):
        """The most important test: a tenant's edit must not be reverted."""
        key = 'test.install_defaults.preserving'
        Setting.objects.create(key=key, value={'a': 'tenant customised value'})

        Setting.install_defaults(key, {'a': 'shipped default'})

        setting = Setting.objects.get(key=key)
        self.assertEqual(setting.value, {'a': 'tenant customised value'})

    def test_additive_new_key_is_added_existing_keys_untouched(self):
        key = 'test.install_defaults.additive'
        Setting.objects.create(key=key, value={'a': 'tenant customised value'})

        Setting.install_defaults(key, {'a': 'shipped default', 'b': 'new key default'})

        setting = Setting.objects.get(key=key)
        self.assertEqual(setting.value, {
            'a': 'tenant customised value',
            'b': 'new key default',
        })

    def test_no_missing_keys_is_a_no_op(self):
        key = 'test.install_defaults.noop'
        Setting.objects.create(key=key, value={'a': 'tenant customised value'})
        before = Setting.objects.get(key=key)
        before_history_count = before.history.count()

        Setting.install_defaults(key, {'a': 'shipped default'})

        after = Setting.objects.get(key=key)
        self.assertEqual(after.value, {'a': 'tenant customised value'})
        # Nothing was missing, so save() must not have been called again.
        self.assertEqual(after.history.count(), before_history_count)

    def test_none_stored_value_does_not_raise(self):
        # The `value` column is NOT NULL at the DB level, so a genuine NULL
        # can't be persisted through the ORM either — but install_defaults()
        # must still guard against it defensively (e.g. a value fetched via
        # some other path, or a future schema relaxation). Simulate that
        # in-memory row via a mocked `.get()` rather than writing NULL to the
        # real table.
        key = 'test.install_defaults.none_value'
        in_memory_setting = Setting(key=key, value=None)
        with mock.patch.object(Setting.objects, 'get', return_value=in_memory_setting), \
                mock.patch.object(Setting, 'save', autospec=True) as mock_save:
            Setting.install_defaults(key, {'a': '1'})

        self.assertEqual(in_memory_setting.value, {'a': '1'})
        mock_save.assert_called_once()

    def test_non_dict_stored_value_does_not_raise(self):
        key = 'test.install_defaults.non_dict_value'
        Setting.objects.create(key=key, value=['not', 'a', 'dict'])

        Setting.install_defaults(key, {'a': '1'})

        setting = Setting.objects.get(key=key)
        self.assertEqual(setting.value, {'a': '1'})

    def _request(self):
        return self.factory.get('/settings/run/', {'report_id': '1'})

    def test_end_to_end_access_request_install_preserves_customisation(self):
        access_request(self._request()).install()
        setting = Setting.objects.get(key=access_request.key)
        setting.value['approved_subject'] = 'Tenant customised subject'
        setting.save()

        access_request(self._request()).install()

        setting.refresh_from_db()
        self.assertEqual(
            setting.value['approved_subject'], 'Tenant customised subject')

    def test_end_to_end_ferpa_install_preserves_customisation(self):
        ferpa(self._request()).install()
        setting = Setting.objects.get(key=ferpa.key)
        setting.value['ferpa_intro'] = 'Tenant customised FERPA intro'
        setting.save()

        ferpa(self._request()).install()

        setting.refresh_from_db()
        self.assertEqual(
            setting.value['ferpa_intro'], 'Tenant customised FERPA intro')
