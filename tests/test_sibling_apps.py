"""Sibling apps cis imports (#100).

alerts is optional and reached only through cis/integrations/alerts.py;
pd_event and student_transactions are required and named by a system check
(cis.E004) when missing, alerts by a warning (cis.W009).
"""
import pathlib
import re
import uuid
from datetime import datetime

from django.utils import timezone
from unittest import mock

from django.apps import apps
from django.test import SimpleTestCase, TestCase

from cis.checks import sibling_apps_check
from cis.integrations import alerts as alerts_integration
from cis.models.customuser import CustomUser

CIS_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _without(*labels):
    configs = {k: v for k, v in apps.app_configs.items() if k not in labels}
    return mock.patch.object(apps, 'app_configs', configs)


class SiblingAppsCheckTests(SimpleTestCase):
    def test_silent_when_all_installed(self):
        self.assertEqual(sibling_apps_check(None), [])

    def test_missing_required_app_is_an_error_naming_it(self):
        with _without('pd_event', 'student_transactions'):
            messages = sibling_apps_check(None)
        self.assertEqual({m.id for m in messages}, {'cis.E004'})
        text = ' '.join(m.msg for m in messages)
        self.assertIn("'pd_event'", text)
        self.assertIn("'student_transactions'", text)

    def test_missing_alerts_is_a_warning(self):
        with _without('alerts'):
            messages = sibling_apps_check(None)
        self.assertEqual([m.id for m in messages], ['cis.W009'])
        self.assertIn("'alerts'", messages[0].msg)


class AlertsIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create(
            username=f'u_{uuid.uuid4().hex[:8]}', email=f'{uuid.uuid4().hex[:8]}@x.com')

    def test_create_alert_writes_one_with_the_app(self):
        from alerts.models import Alert
        alert = alerts_integration.create_alert('t_type', self.user, 'hello')
        self.assertIsNotNone(alert)
        row = Alert.objects.get(pk=alert.pk)
        self.assertEqual((row.alert_type, row.recipient, row.message),
                         ('t_type', self.user, 'hello'))

    def test_mark_alerts_read_stamps_only_unread_matches(self):
        alert = alerts_integration.create_alert('t_type', self.user, 'app 123')
        alerts_integration.create_alert('other', self.user, 'app 123')
        now = timezone.now()
        self.assertEqual(alerts_integration.mark_alerts_read(
            now, alert_type='t_type', message__contains='123'), 1)
        alert.refresh_from_db()
        self.assertIsNotNone(alert.read_on)

    def test_noop_without_the_app(self):
        from alerts.models import Alert
        before = Alert.objects.count()
        with _without('alerts'):
            self.assertIsNone(alerts_integration.alert_model())
            self.assertIsNone(alerts_integration.create_alert('t', self.user, 'm'))
            self.assertEqual(alerts_integration.mark_alerts_read(datetime.now()), 0)
        self.assertEqual(Alert.objects.count(), before)


class NoDirectImportsTests(SimpleTestCase):
    """Guards the seams: these apps are reached only where documented."""

    def _offenders(self, pattern, allowed=(), module_level_only=False):
        regex = re.compile(pattern)
        found = []
        for path in CIS_ROOT.rglob('*.py'):
            rel = path.relative_to(CIS_ROOT).as_posix()
            if rel.startswith(('tests/', 'migrations/', 'build/')) or rel in allowed:
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if module_level_only and line[:1].isspace():
                    continue
                if regex.match(line.strip()):
                    found.append(f'{rel}:{n}')
        return found

    def test_alerts_only_through_the_integration(self):
        self.assertEqual(self._offenders(r'(from|import) alerts\b'), [])

    def test_no_module_level_student_transactions_import(self):
        # Lazy imports keep cis importable, so cis.E004 can name the app.
        self.assertEqual(self._offenders(
            r'(from|import) student_transactions\b', module_level_only=True,
            allowed=('reports/transactions.py',)), [])
