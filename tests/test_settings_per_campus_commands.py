"""#129: commands that read per-campus settings run for one campus."""
import uuid
from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from cis.campus_context import current_campus_or_none
from cis.management.campus_command import CampusCommand
from cis.models.course import Campus

COMMANDS = ['import_class_sections', 'import_from_sis', 'export_student_data',
            'import_student_id_from_ethos']


class CampusCommandTests(TestCase):
    def test_commands_are_campus_commands(self):
        import importlib
        for name in COMMANDS:
            module = importlib.import_module(f'cis.management.commands.{name}')
            self.assertTrue(issubclass(module.Command, CampusCommand), name)

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_requires_a_campus(self):
        with self.assertRaises(CommandError):
            call_command('export_student_data', stdout=StringIO())


@override_settings(MULTI_CAMPUS=True)
class InitDocumentTypesPerCampusTests(TestCase):
    def test_reads_support_docs_inside_each_campus(self):
        campuses = [Campus.objects.create(
            name=f'C{i}-{uuid.uuid4().hex[:6]}',
            code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}') for i in (1, 2)]
        seen = []

        def types():
            seen.append(current_campus_or_none())
            return []

        with mock.patch('cis.settings.support_docs.support_docs.get_types', side_effect=types):
            call_command('init_document_types', dry_run=True, stdout=StringIO())
        self.assertTrue({c.pk for c in campuses} <= {c.pk for c in seen if c})
