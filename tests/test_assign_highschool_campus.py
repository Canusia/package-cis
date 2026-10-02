"""assign_highschool_campus: link schools to a named campus (create-only)."""
import uuid
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from cis.models.course import Campus
from cis.models.highschool import HighSchool, HighSchoolCampus


def _campus():
    return Campus.objects.create(
        name=f'C-{uuid.uuid4().hex[:8]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}_{uuid.uuid4().hex[:6]}')


def _hs(name):
    hs = HighSchool.objects.create(name=name, code=uuid.uuid4().hex[:8])
    # The new-school signal may auto-link; these tests set links explicitly.
    HighSchoolCampus.objects.filter(highschool=hs).delete()
    return hs


def _run(*args):
    out = StringIO()
    call_command('assign_highschool_campus', *args, stdout=out, stderr=out)
    return out.getvalue()


class AssignHighSchoolCampusTests(TestCase):
    def setUp(self):
        self.campus = _campus()
        self.other = _campus()
        self.h1, self.h2, self.h3 = _hs('One'), _hs('Two'), _hs('Three')

    def links(self, campus=None):
        return HighSchoolCampus.objects.filter(campus=campus or self.campus)

    def test_unknown_campus_is_command_error(self):
        with self.assertRaises(CommandError):
            _run('--campus', 'NOPE', '--all')

    def test_requires_all_or_ids(self):
        with self.assertRaises(CommandError):
            _run('--campus', self.campus.code)
        with self.assertRaises(CommandError):
            _run('--campus', self.campus.code, '--all', '--ids', str(self.h1.pk))

    def test_all_links_every_school_active(self):
        out = _run('--campus', self.campus.code, '--all')
        for hs in (self.h1, self.h2, self.h3):
            link = self.links().get(highschool=hs)
            self.assertEqual(link.status, 'Active')
            self.assertEqual(link.building_code, '')
        self.assertIn('linked', out)

    def test_dry_run_writes_nothing(self):
        out = _run('--campus', self.campus.code, '--all', '--dry-run')
        self.assertEqual(self.links().count(), 0)
        self.assertIn('would', out)

    def test_ids_links_only_those(self):
        _run('--campus', self.campus.code, '--ids', f'{self.h1.pk},{self.h2.pk}')
        self.assertEqual(
            set(self.links().values_list('highschool_id', flat=True)),
            {self.h1.pk, self.h2.pk})

    def test_bad_or_missing_ids_are_command_errors(self):
        with self.assertRaises(CommandError):
            _run('--campus', self.campus.code, '--ids', 'not-a-uuid')
        with self.assertRaises(CommandError):
            _run('--campus', self.campus.code, '--ids', str(uuid.uuid4()))
        self.assertEqual(self.links().count(), 0)

    def test_building_code_and_status_with_single_id(self):
        _run('--campus', self.campus.code, '--ids', str(self.h1.pk),
             '--building-code', 'B1', '--status', 'Inactive')
        link = self.links().get(highschool=self.h1)
        self.assertEqual((link.building_code, link.status), ('B1', 'Inactive'))

    def test_building_code_rejected_with_all_or_several_ids(self):
        with self.assertRaises(CommandError):
            _run('--campus', self.campus.code, '--all', '--building-code', 'B1')
        with self.assertRaises(CommandError):
            _run('--campus', self.campus.code, '--ids',
                 f'{self.h1.pk},{self.h2.pk}', '--building-code', 'B1')
        self.assertEqual(self.links().count(), 0)

    def test_already_linked_is_skipped_and_untouched(self):
        existing = HighSchoolCampus.objects.create(
            highschool=self.h1, campus=self.campus, building_code='KEEP',
            status='Inactive')
        out = _run('--campus', self.campus.code, '--all')
        existing.refresh_from_db()
        self.assertEqual((existing.building_code, existing.status), ('KEEP', 'Inactive'))
        self.assertEqual(self.links().count(), 3)
        self.assertIn('skipped', out)

    def test_building_code_on_already_linked_is_skipped_not_modified(self):
        existing = HighSchoolCampus.objects.create(
            highschool=self.h1, campus=self.campus, building_code='KEEP')
        out = _run('--campus', self.campus.code, '--ids', str(self.h1.pk),
                   '--building-code', 'NEW', '--status', 'Inactive')
        existing.refresh_from_db()
        self.assertEqual((existing.building_code, existing.status), ('KEEP', 'Active'))
        self.assertIn('skipped', out)

    def test_building_code_clash_is_a_clear_error_not_a_traceback(self):
        HighSchoolCampus.objects.create(
            highschool=self.h2, campus=self.campus, building_code='B1')
        out = _run('--campus', self.campus.code, '--ids', str(self.h1.pk),
                   '--building-code', 'B1')
        self.assertFalse(self.links().filter(highschool=self.h1).exists())
        self.assertIn('B1', out)
        self.assertIn('Two', out)

    def test_same_code_on_another_campus_is_fine(self):
        HighSchoolCampus.objects.create(
            highschool=self.h2, campus=self.other, building_code='B1')
        _run('--campus', self.campus.code, '--ids', str(self.h1.pk),
             '--building-code', 'B1')
        self.assertTrue(self.links().filter(highschool=self.h1, building_code='B1').exists())

    def test_rerun_is_idempotent(self):
        _run('--campus', self.campus.code, '--all')
        n = self.links().count()
        _run('--campus', self.campus.code, '--all')
        self.assertEqual(self.links().count(), n)
