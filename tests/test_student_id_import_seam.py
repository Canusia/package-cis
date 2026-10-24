"""Student-ID import strategy (#93): a tenant's
services/student_id_import.py import_student_ids(configs) runs instead of
the Ethos lookup, under the same setting and cron job."""
from unittest import mock

from django.test import TestCase

from cis.management.commands import import_student_id_from_ethos as cmd

CONFIGS = {'is_active': 'Yes', 'notification_list': ''}


class StudentIdImportSeamTests(TestCase):
    def _run(self, override):
        with mock.patch.object(cmd.student_id_importer, 'from_db', return_value=CONFIGS), \
                mock.patch.object(cmd, 'get_tenant_override', override), \
                mock.patch.object(cmd, 'get_tenant_service') as service, \
                mock.patch.object(cmd, 'PrivateMediaStorage') as storage, \
                mock.patch.object(cmd, 'get_s3_url', return_value='url'), \
                mock.patch.object(cmd, 'cron_task_started'), \
                mock.patch.object(cmd, 'cron_task_done') as done:
            storage.return_value.save.return_value = 'path'
            cmd.Command().handle(time='2026-10-24 12:00:00')
        return service, done.send.call_args.kwargs

    def test_tenant_import_replaces_the_ethos_lookup(self):
        seen = {}

        def import_student_ids(configs):
            seen['configs'] = configs
            return ['Imported 1 ID.'], [{'id': 's1', 'RESULT': 'Updated'}]

        service, done = self._run(
            lambda m, a: import_student_ids
            if (m, a) == ('student_id_import', 'import_student_ids') else None)
        service.assert_not_called()
        self.assertEqual(seen['configs'], CONFIGS)
        self.assertIn('Imported 1 ID.', done['summary'])
        self.assertIn('Results file: url', done['summary'])

    def test_without_a_tenant_import_ethos_is_used(self):
        with mock.patch.object(cmd, 'ethos_enabled', return_value=True):
            service, _ = self._run(lambda m, a: None)
        service.assert_called_with('ethos_identity')
