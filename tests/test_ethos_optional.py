"""ethos is optional (#85, #114 item 1).

cis must import, route and migrate on a tenant without the ethos app. These
tests simulate the missing app by patching ``cis.integrations.ethos`` (or the
app registry, for the load-time checks of migration 0056) and assert that the
SIS actions hide themselves or answer with a clear message, the academic-year
SIS import card is left out, and the ethos-backed commands skip cleanly.
"""
import importlib.util
import json
import sys
import uuid
from unittest import mock, skipUnless

from django.apps import apps
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from cis.integrations import ethos as ethos_integration
from cis.models.customuser import CustomUser
from cis.models.term import AcademicYear, Term

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

# The with-ethos cases need the real app; skip them on a host without it (#131).
needs_ethos = skipUnless(ethos_integration.ethos_enabled(), 'needs the ethos app')

DISABLED = mock.patch('cis.integrations.ethos.ethos_enabled', return_value=False)


def _sfx():
    return uuid.uuid4().hex[:8]


class _NoLoginHistory:
    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)


class DetectionTests(SimpleTestCase):
    def test_absent_parent_is_not_installed(self):
        # find_spec('ethos.ethos') raises when 'ethos' itself is missing; the
        # detector must check the parent first and report "absent".
        with mock.patch.dict(sys.modules, {'ethos': None}):
            self.assertIsNone(ethos_integration._detect_ethos_root())

    def test_flat_layout_when_nested_lookup_fails(self):
        real = importlib.util.find_spec

        def fake(name, *a, **kw):
            if name == 'ethos':
                return object()
            if name == 'ethos.ethos':
                raise ModuleNotFoundError(name)
            return real(name, *a, **kw)

        with mock.patch('importlib.util.find_spec', side_effect=fake):
            self.assertEqual(ethos_integration._detect_ethos_root(), 'ethos')

    def test_not_enabled_without_the_app(self):
        configs = {k: v for k, v in apps.app_configs.items() if k != 'ethos'}
        with mock.patch.object(apps, 'app_configs', configs):
            self.assertFalse(ethos_integration.ethos_app_installed())
            self.assertFalse(ethos_integration.ethos_enabled())
            self.assertIsNone(ethos_integration.ethos_module('library.ethos'))
            self.assertIsNone(ethos_integration.ethos_client_class())
            self.assertIsNone(ethos_integration.import_sections_task())
            self.assertIsNone(ethos_integration.ethos_log_model())
            exc = ethos_integration.ethos_not_configured_error()
            self.assertTrue(issubclass(exc, Exception))

    @needs_ethos
    def test_enabled_on_this_deployment(self):
        # The host test settings install ethos; the helpers resolve the real code.
        self.assertTrue(ethos_integration.ethos_enabled())
        self.assertIsNotNone(ethos_integration.ethos_client_class())
        self.assertEqual(ethos_integration.ethos_not_configured_error().__name__,
                         'EthosNotConfigured')


class Migration0056Tests(SimpleTestCase):
    """0056 decides at load time whether to depend on ethos and add mirror_logs."""

    PATH = 'cis.migrations.0056_studentregistration_mirror_fields'

    def _load(self, with_ethos):
        spec = importlib.util.find_spec(self.PATH)
        configs = dict(apps.app_configs)
        if not with_ethos:
            configs.pop('ethos', None)
        with mock.patch.object(apps, 'app_configs', configs):
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return module.Migration

    def test_import_before_apps_ready_raises(self):
        # An early import must not silently take the no-ethos branch.
        from django.core.exceptions import AppRegistryNotReady
        spec = importlib.util.find_spec(self.PATH)
        with mock.patch.object(apps, 'apps_ready', False), \
                mock.patch.object(apps, 'app_configs', {}):
            module = importlib.util.module_from_spec(spec)
            with self.assertRaises(AppRegistryNotReady):
                spec.loader.exec_module(module)

    def test_without_ethos_no_reference_to_ethos(self):
        migration = self._load(with_ethos=False)
        self.assertEqual([d[0] for d in migration.dependencies], ['cis'])
        self.assertEqual([op.name for op in migration.operations],
                         ['last_mirror_at', 'last_mirror_error', 'last_mirror_status'])

    @needs_ethos
    def test_with_ethos_unchanged(self):
        migration = self._load(with_ethos=True)
        self.assertIn(('ethos', '0003_resource_preferred_representation'),
                      migration.dependencies)
        self.assertEqual([op.name for op in migration.operations],
                         ['last_mirror_at', 'last_mirror_error', 'last_mirror_status',
                          'mirror_logs'])


class RegistrationMirrorLogsTests(SimpleTestCase):
    def test_prefetch_skips_mirror_logs_without_ethos(self):
        from cis.views.eager import registration_prefetch_related
        with mock.patch('cis.integrations.ethos.ethos_log_model', return_value=None):
            lookups = [p.prefetch_through for p in registration_prefetch_related()]
        self.assertNotIn('mirror_logs', lookups)

    @needs_ethos
    def test_prefetch_keeps_mirror_logs_with_ethos(self):
        from cis.views.eager import registration_prefetch_related
        lookups = [p.prefetch_through for p in registration_prefetch_related()]
        self.assertIn('mirror_logs', lookups)

    def test_failed_mirror_serializer_has_no_last_log_without_ethos(self):
        from cis.serializers.registration import FailedMirrorRegistrationSerializer
        obj = mock.Mock()
        with DISABLED:
            self.assertIsNone(FailedMirrorRegistrationSerializer()._last_log(obj))
        obj.mirror_logs.order_by.assert_not_called()


class SisActionsHiddenTests(_NoLoginHistory, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create(
            username=f'ce_{_sfx()}@x.com', email=f'ce_{_sfx()}@x.com', is_active=True)
        cls.admin.groups.add(Group.objects.get_or_create(name='ce')[0])
        cls.ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        cls.term = Term.objects.create(academic_year=cls.ay, code='24/FA', label='Fall')

    def _slugs(self, registry):
        return {slug for group in registry.for_scope('detail', self.admin).values()
                for slug in group['actions']}

    def test_term_sis_actions_hidden_without_ethos(self):
        from myce.component_registry.term import term_actions
        self.assertTrue({'lookup_sis_id', 'pull_sub_terms'} <= self._slugs(term_actions))
        with DISABLED:
            slugs = self._slugs(term_actions)
        self.assertNotIn('lookup_sis_id', slugs)
        self.assertNotIn('pull_sub_terms', slugs)

    def test_student_and_registration_sis_actions_hidden_without_ethos(self):
        from myce.component_registry.registration import registration_actions
        from myce.component_registry.student import student_actions
        with DISABLED:
            self.assertFalse({'lookup_sis_id', 'lookup_by_banner_id'}
                             & self._slugs(student_actions))
            self.assertNotIn('lookup_section_registration_id',
                             self._slugs(registration_actions))

    @mock.patch('cis.actions.term.Ethos')
    def test_term_action_called_directly_answers_clearly(self, MockEthos):
        from cis.actions.term import lookup_sis_id, pull_sub_terms
        request = RequestFactory().post('/', {'ids[]': [str(self.term.id)]})
        request.user = self.admin
        with DISABLED:
            for action in (lookup_sis_id, pull_sub_terms):
                body = json.loads(action(request).content)
                self.assertEqual(body['status'], 'error')
                self.assertEqual(body['message'], ethos_integration.ETHOS_MISSING_MESSAGE)
        MockEthos.assert_not_called()

    @mock.patch('cis.actions.term.Ethos')
    def test_dispatch_refuses_without_calling_ethos(self, MockEthos):
        self.client.force_login(self.admin)
        with DISABLED:
            resp = self.client.post(reverse('cis:term_bulk_actions'), {
                'action': 'lookup_sis_id', 'ids[]': [str(self.term.id)]})
        self.assertEqual(resp.status_code, 403)
        MockEthos.assert_not_called()


class AcademicYearAddNewTemplateTests(_NoLoginHistory, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create(
            username=f'ce_{_sfx()}@x.com', email=f'ce_{_sfx()}@x.com', is_active=True)
        cls.admin.groups.add(Group.objects.get_or_create(name='ce')[0])

    def setUp(self):
        self.client.force_login(self.admin)

    @needs_ethos
    def test_sis_import_card_rendered_with_ethos(self):
        resp = self.client.get(reverse('cis:academic_year_add_new'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Import from SIS')
        self.assertContains(resp, reverse('ethos:lookup_academic_period'))

    def test_sis_import_card_left_out_without_ethos(self):
        # Without the ethos app, reversing ethos: URLs would raise NoReverseMatch.
        with DISABLED:
            resp = self.client.get(reverse('cis:academic_year_add_new'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Import from SIS')
        self.assertNotContains(resp, 'sis-lookup-btn')
        self.assertNotContains(resp, '/ce/ethos/')


class CommandsWithoutEthosTests(SimpleTestCase):
    def test_import_class_sections_skips(self):
        from cis.management.commands import import_class_sections as cmd
        cfg = {'is_active': 'Yes', 'terms': ['x']}
        with mock.patch.object(cmd.class_section_importer, 'from_db', return_value=cfg), \
                mock.patch.object(cmd, 'import_sections_task', return_value=None), \
                mock.patch.object(cmd, 'cron_task_started'), \
                mock.patch.object(cmd, 'cron_task_done') as done, \
                mock.patch.object(cmd.Term.objects, 'filter') as terms:
            cmd.Command().handle(time='2026-10-24 12:00:00')
        terms.assert_not_called()
        summary = done.send.call_args.kwargs['summary']
        self.assertIn(ethos_integration.ETHOS_MISSING_MESSAGE, summary)

    def test_import_student_id_from_ethos_skips(self):
        from cis.management.commands import import_student_id_from_ethos as cmd
        with mock.patch.object(cmd.student_id_importer, 'from_db',
                               return_value={'is_active': 'Yes'}), \
                mock.patch.object(cmd, 'ethos_enabled', return_value=False), \
                mock.patch.object(cmd, 'get_tenant_service') as svc, \
                mock.patch.object(cmd, 'cron_task_started'), \
                mock.patch.object(cmd, 'cron_task_done') as done:
            cmd.Command().handle(time='2026-10-24 12:00:00')
        svc.assert_not_called()
        summary = done.send.call_args.kwargs['summary']
        self.assertIn(ethos_integration.ETHOS_MISSING_MESSAGE, summary)
