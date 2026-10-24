"""Startup tolerance for missing tenant modules (package-cis#97).

A tenant adopting the package used to need every module cis expects before
anything worked: table configs were resolved when the views modules were
imported, so one missing module broke every cis URL; `onboarding_steps` and
the host component registries had no fallback; and an unset
TENANT_SERVICES_APP failed startup.

`cis.tests.fake_tenant` stands in for a tenant that ships only a handful of
service modules and no table configs at all.
"""
import ast
import os
import subprocess
import sys
import uuid
import warnings
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings

from cis import component_registries
from cis.checks import REQUIRED_TENANT_SERVICES, tenant_modules_check
from cis.services.table_configs import (
    REQUIRED_TABLE_CONFIGS, OPTIONAL_TABLE_CONFIGS, MissingTableConfig,
    get_table_config, lazy_table_config,
)
from cis.services.tenant_services import (
    MissingTenantService, get_tenant_override, get_tenant_service,
    tenant_services_app,
)

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

FAKE = 'cis.tests.fake_tenant'
CIS_ROOT = Path(__file__).resolve().parent.parent


def _package_sources():
    """(relative path, parsed tree) for every shipped cis module."""
    for path in sorted(CIS_ROOT.rglob('*.py')):
        rel = path.relative_to(CIS_ROOT)
        if rel.parts[0] in ('tests', 'migrations', 'build', 'dist'):
            continue
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', SyntaxWarning)
            yield rel, ast.parse(path.read_text(), filename=str(path))


class TenantServicesAppDefaultTests(SimpleTestCase):

    def test_defaults_to_table_configs_app_when_unset(self):
        with self.settings(TABLE_CONFIGS_APP=FAKE):
            del settings.TENANT_SERVICES_APP
            self.assertEqual(tenant_services_app(), FAKE)
            mod = get_tenant_service('highschool_types')
        self.assertEqual(mod.__name__, f'{FAKE}.services.highschool_types')

    def test_an_explicit_setting_wins(self):
        with self.settings(TABLE_CONFIGS_APP='elsewhere', TENANT_SERVICES_APP=FAKE):
            self.assertEqual(tenant_services_app(), FAKE)


@override_settings(TENANT_SERVICES_APP=FAKE, TABLE_CONFIGS_APP=FAKE)
class MissingModuleErrorTests(SimpleTestCase):

    def test_missing_tenant_service_names_the_module(self):
        with self.assertRaises(MissingTenantService) as ctx:
            get_tenant_service('registration_form')
        exc = ctx.exception
        # Both: callers that treat absence as "not adopted" keep working.
        self.assertIsInstance(exc, ModuleNotFoundError)
        self.assertIsInstance(exc, ImproperlyConfigured)
        self.assertEqual(exc.name, f'{FAKE}.services.registration_form')
        self.assertIn(f'{FAKE}.services.registration_form', str(exc))

    def test_override_still_yields_none_for_a_missing_module(self):
        self.assertIsNone(get_tenant_override('roster_status_form', 'anything'))

    def test_missing_table_config_names_the_module(self):
        with self.assertRaises(MissingTableConfig) as ctx:
            get_table_config('districts_table')
        exc = ctx.exception
        self.assertIsInstance(exc, ModuleNotFoundError)
        self.assertIsInstance(exc, ImproperlyConfigured)
        self.assertEqual(exc.name, f'{FAKE}.services.districts_table')
        self.assertIn('services/districts_table.py', str(exc))

    def test_lazy_table_config_imports_nothing_until_called(self):
        build = lazy_table_config('districts_table')  # does not raise
        with self.assertRaisesMessage(ImproperlyConfigured, 'districts_table'):
            build(variant='districts_index', api_url='/x')


class LazyTableConfigTests(SimpleTestCase):

    def test_call_and_signature_follow_the_tenant_function(self):
        import inspect
        real = get_table_config('districts_table').build_config
        build = lazy_table_config('districts_table')
        self.assertEqual(inspect.signature(build), inspect.signature(real))
        self.assertEqual(
            build(variant='districts_index', api_url='/x'),
            real(variant='districts_index', api_url='/x'))


class NoImportTimeResolutionTests(SimpleTestCase):
    """Guard: no cis module resolves a tenant module at import time, which is
    what turned one missing module into a dead URLconf."""

    RESOLVERS = {'get_table_config', 'get_tenant_service'}

    def _module_level_calls(self, tree):
        """Calls outside any function body (class bodies run at import)."""
        found = []

        def walk(node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    continue
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Name)
                        and child.func.id in self.RESOLVERS):
                    found.append(child.lineno)
                walk(child)
        walk(tree)
        return found

    def test_no_module_level_resolution(self):
        offenders = []
        for rel, tree in _package_sources():
            offenders += [f'{rel}:{line}' for line in self._module_level_calls(tree)]
        self.assertEqual(offenders, [])

    def test_every_table_config_cis_names_is_listed(self):
        """REQUIRED/OPTIONAL_TABLE_CONFIGS drive check W010; a table added
        without listing it would go unchecked."""
        named = set()
        for _, tree in _package_sources():
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                        and node.args[0].value.endswith('_table')
                        and getattr(node.func, 'id', None) in (
                            'get_table_config', 'lazy_table_config',
                            '_optional_table_config', '_optional_users_tab_check')):
                    named.add(node.args[0].value)
        self.assertEqual(named - set(REQUIRED_TABLE_CONFIGS) - set(OPTIONAL_TABLE_CONFIGS), set())


class UrlconfImportTests(SimpleTestCase):

    def test_cis_urls_import_for_a_tenant_missing_modules(self):
        """In a fresh interpreter: the fake tenant ships no table configs and
        none of registration_form / ferpa_form / verify_email_form, and cis.urls
        still imports."""
        code = (
            'import django\n'
            'django.setup()\n'
            'from django.conf import settings\n'
            f'settings.TABLE_CONFIGS_APP = {FAKE!r}\n'
            f'settings.TENANT_SERVICES_APP = {FAKE!r}\n'
            'import cis.urls\n'
            'print("URLCONF-OK")\n'
        )
        env = dict(os.environ)
        env.setdefault('DJANGO_SETTINGS_MODULE', 'myce.settings')
        result = subprocess.run(
            [sys.executable, '-c', code], cwd=settings.BASE_DIR, env=env,
            capture_output=True, text=True, timeout=300)
        self.assertIn('URLCONF-OK', result.stdout, result.stderr[-3000:])


class MissingTableConfigPageTests(TestCase):

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

    def setUp(self):
        sfx = uuid.uuid4().hex[:8]
        self.ce = get_user_model().objects.create_user(
            username=f'ce_{sfx}', email=f'ce_{sfx}@x.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.client.force_login(self.ce)

    def test_only_the_page_needing_the_config_fails_with_a_clear_error(self):
        with override_settings(TABLE_CONFIGS_APP=FAKE):
            with self.assertRaisesMessage(
                    ImproperlyConfigured, f'{FAKE}.services.districts_table'):
                self.client.get('/ce/districts/')
        self.assertEqual(self.client.get('/ce/districts/').status_code, 200)


class TenantModulesCheckTests(SimpleTestCase):

    def _ids(self, messages):
        return [(m.id, m.msg) for m in messages]

    def test_silent_for_a_tenant_shipping_everything(self):
        self.assertEqual(self._ids(tenant_modules_check(None)), [])

    @override_settings(TABLE_CONFIGS_APP=FAKE, TENANT_SERVICES_APP=FAKE)
    def test_names_each_missing_module(self):
        found = self._ids(tenant_modules_check(None))
        w010 = [msg for cid, msg in found if cid == 'cis.W010']
        w011 = [msg for cid, msg in found if cid == 'cis.W011']
        self.assertEqual(len(w010), len(REQUIRED_TABLE_CONFIGS))
        self.assertIn(f'Table config {FAKE}.services.courses_table is missing.', w010)
        self.assertIn(
            f'Tenant service module {FAKE}.services.registration_form is missing.', w011)
        self.assertIn(
            f'Tenant service module {FAKE}.services.onboarding_steps is missing.', w011)
        # The fake tenant ships these.
        for shipped in ('highschool_types', 'recommendation_form', 'student_profile_form'):
            self.assertNotIn(
                f'Tenant service module {FAKE}.services.{shipped} is missing.', w011)
        self.assertEqual(
            len(w011), len(REQUIRED_TENANT_SERVICES) - 3)

    def test_names_a_missing_registry_cis_has_no_default_for(self):
        real = component_registries.host_has
        with mock.patch.object(component_registries, 'host_has',
                               lambda name: name != 'course' and real(name)):
            found = self._ids(tenant_modules_check(None))
        self.assertEqual(
            found, [('cis.W012', 'myce.component_registry.course is missing.')])


class OnboardingStepsFallbackTests(SimpleTestCase):

    @override_settings(TENANT_SERVICES_APP=FAKE)
    def test_startup_registers_no_steps_without_a_catalog(self):
        from cis.signals import onboarding
        with mock.patch.object(onboarding, 'register') as register, \
                mock.patch.object(onboarding.handlers, 'register') as wire, \
                self.assertLogs('cis.signals.onboarding', 'WARNING') as logs:
            onboarding.register_handlers()
        register.assert_not_called()
        wired = [c.args[0] for c in wire.call_args_list]
        self.assertEqual(wired, [onboarding.events.APPLICATION_STARTED,
                                 onboarding.events.EMAIL_VERIFIED])
        self.assertIn(f'{FAKE}.services.onboarding_steps', logs.output[0])


class ComponentRegistryDefaultTests(SimpleTestCase):

    def test_host_modules_win(self):
        """ewu ships every registry: nothing is replaced."""
        import myce.component_registry.registration as host
        self.assertEqual(component_registries.install_defaults(), [])
        self.assertFalse(getattr(host, '__cis_default__', False))
        self.assertEqual(component_registries.missing_registries(), [])

    def test_stands_in_for_a_registry_the_host_lacks(self):
        import myce.component_registry as parent
        dotted = 'myce.component_registry.access_request'
        saved = parent.__dict__.get('access_request')
        real = component_registries.host_has
        try:
            with mock.patch.dict(sys.modules), \
                    mock.patch.object(component_registries, 'host_has',
                                      lambda name: name != 'access_request' and real(name)):
                sys.modules.pop(dotted, None)
                sys.modules.pop('cis.tabs.access_request', None)
                self.assertEqual(component_registries.install_defaults(), ['access_request'])
                component_registries.load_defaults(['access_request'])

                from myce.component_registry.access_request import (
                    access_request_actions, access_request_tabs,
                )
                self.assertTrue(sys.modules[dotted].__cis_default__)
                self.assertEqual(type(access_request_actions).__name__, 'ActionRegistry')
                # cis's own tabs registered into the stand-in.
                self.assertTrue(access_request_tabs._tabs)
                # Idempotent.
                self.assertEqual(component_registries.install_defaults(), [])
        finally:
            if saved is not None:
                parent.access_request = saved

    def test_ready_installs_defaults_before_it_loads_them(self):
        from django.apps import apps
        self.assertEqual(apps.get_app_config('cis').default_registries, [])
