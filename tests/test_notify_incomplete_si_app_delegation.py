"""`cis` must not shadow instructor_app's notify_incomplete_si_app.

Both packages ship a command by this name. Django's ``get_commands()`` iterates
``reversed(apps.get_app_configs())``, so whichever app appears *earlier* in
INSTALLED_APPS wins — `cis` (settings.py:167) beats `instructor_app` (:178) on a
default tenant. The `cis` implementation queries the legacy
``cis.models.teacher_applicant`` tables, which are empty on any tenant whose
applications live in instructor_app, so the cron ran green and sent nothing.

The fix keeps the name resolvable but hands the behaviour to instructor_app when
that app is installed, falling back to the legacy body when it is not — the
decision is made per installation rather than per release, so a tenant still on
the legacy models is unaffected.
"""
from unittest import skipIf

from django.test import SimpleTestCase

from cis.management.commands import notify_incomplete_si_app as cmd_module

INSTRUCTOR_APP_COMMAND = cmd_module._load_instructor_app_command()


class LoaderTests(SimpleTestCase):
    def test_returns_none_when_no_candidate_module_exists(self):
        original = cmd_module._CANDIDATES
        cmd_module._CANDIDATES = ('cis.does_not_exist.management.commands.nope',)
        try:
            self.assertIsNone(cmd_module._load_instructor_app_command())
        finally:
            cmd_module._CANDIDATES = original

    def test_legacy_implementation_is_retained(self):
        # Tenants without instructor_app still need the original behaviour.
        self.assertTrue(hasattr(cmd_module, '_LegacyCommand'))
        self.assertTrue(hasattr(cmd_module._LegacyCommand, 'handle'))


@skipIf(INSTRUCTOR_APP_COMMAND is None, 'instructor_app is not installed')
class DelegationTests(SimpleTestCase):
    def test_command_is_the_instructor_app_implementation(self):
        self.assertIs(cmd_module.Command, INSTRUCTOR_APP_COMMAND)

    def test_command_is_not_the_legacy_implementation(self):
        self.assertIsNot(cmd_module.Command, cmd_module._LegacyCommand)

    def test_dry_run_is_reachable_through_the_cis_name(self):
        # Delegation must be functional, not nominal: instructor_app's argument
        # surface (--dry-run, and -t defaulting to now) has to come with it.
        parser = cmd_module.Command().create_parser(
            'manage.py', 'notify_incomplete_si_app')
        help_text = parser.format_help()
        self.assertIn('--dry-run', help_text)
        self.assertIn('--time', help_text)


class ResolutionTests(SimpleTestCase):
    """Guard the outcome users actually care about."""

    @skipIf(INSTRUCTOR_APP_COMMAND is None, 'instructor_app is not installed')
    def test_running_the_name_reaches_instructor_app(self):
        from django.core.management import load_command_class, get_commands

        app_name = get_commands()['notify_incomplete_si_app']
        command = load_command_class(app_name, 'notify_incomplete_si_app')
        self.assertIsInstance(command, INSTRUCTOR_APP_COMMAND)
