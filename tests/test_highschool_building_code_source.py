"""The campus link's building code is the one source of truth.

The section importer resolves a building code through the campus link first
(``highschool_for_building_code``); the school's legacy ``sau`` is only a
single-campus fallback. So every writer of a building code must land it on the
link: the add form and the CSV import seed it, and the edit form no longer
offers ``sau`` (it is edited per campus on the Campuses tab).
"""
import csv
import io
import uuid

from django.conf import settings
from django.test import TestCase, override_settings

from cis.campus_context import campus_context
from cis.forms.highschool import HSModelForm
from cis.models.course import Campus
from cis.models.highschool import HighSchool, HighSchoolCampus
from cis.services.importers.highschool_importer import HighSchoolImporter
from cis.signals.highschool_campus import link_new_highschools


def _campus():
    return Campus.objects.create(
        name=f'C-{uuid.uuid4().hex[:8]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}_{uuid.uuid4().hex[:6]}')


def _hs(sau='', name='S', **kw):
    return HighSchool.objects.create(
        name=name, code=uuid.uuid4().hex[:8], sau=sau, **kw)


def _link_code(hs, campus=None):
    links = HighSchoolCampus.objects.filter(highschool=hs)
    if campus is not None:
        links = links.filter(campus=campus)
    return links.get().building_code


class EditFormTests(TestCase):
    def test_existing_school_sau_is_not_editable(self):
        hs = _hs(sau='B100')
        form = HSModelForm(instance=hs)
        self.assertTrue(form.fields['sau'].disabled)
        self.assertIn('Campuses tab', form.fields['sau'].help_text)

    def test_posted_sau_is_ignored_on_edit(self):
        _campus()
        hs = _hs(sau='B100', name='Edit Me')
        data = {f: v for f, v in HSModelForm(instance=hs).initial.items()
                if v is not None and not isinstance(v, (list, tuple))}
        data.update({'name': 'Edit Me', 'sau': 'CHANGED'})
        form = HSModelForm(data, instance=hs)
        if form.is_valid():
            form.save()
        self.assertEqual(HighSchool.objects.get(pk=hs.pk).sau, 'B100')

    def test_add_form_keeps_sau_editable(self):
        self.assertFalse(HSModelForm().fields['sau'].disabled)


@override_settings(MULTI_CAMPUS=False)
class NewSchoolSeedsLinkCodeTests(TestCase):
    def setUp(self):
        self.campus = _campus()

    def test_new_school_link_gets_its_sau(self):
        self.assertEqual(_link_code(_hs(sau=' B200 ')), 'B200')

    def test_placeholder_and_blank_sau_leave_code_empty(self):
        for sau in ('', '-', ' - '):
            self.assertEqual(_link_code(_hs(sau=sau)), '', repr(sau))

    def test_overlong_sau_leaves_code_empty(self):
        self.assertEqual(_link_code(_hs(sau='X' * 21)), '')

    def test_code_held_by_another_school_is_left_empty(self):
        _hs(sau='B300', name='First')
        with self.assertLogs('cis.signals.highschool_campus', 'WARNING'):
            second = _hs(sau='B300', name='Second')
        self.assertEqual(_link_code(second), '')

    def test_bulk_created_schools_get_their_codes_once_each(self):
        _hs(sau='B400', name='Holder')
        batch = HighSchool.objects.bulk_create([
            HighSchool(name='Bulk 1', code=uuid.uuid4().hex[:8], sau='B401'),
            HighSchool(name='Bulk 2', code=uuid.uuid4().hex[:8], sau='B401'),
            HighSchool(name='Bulk 3', code=uuid.uuid4().hex[:8], sau='B400'),
        ])
        link_new_highschools(batch)
        codes = [_link_code(hs) for hs in batch]
        self.assertEqual(codes, ['B401', '', ''])


@override_settings(MULTI_CAMPUS=True)
class NewSchoolMultiCampusTests(TestCase):
    def test_link_on_the_current_campus_gets_the_sau(self):
        a, _ = _campus(), _campus()
        with campus_context(a):
            hs = _hs(sau='M100')
        self.assertEqual(_link_code(hs, a), 'M100')


def _import(rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=['name', 'code', 'sau'])
    writer.writeheader()
    writer.writerows(rows)
    out.seek(0)
    return HighSchoolImporter().process_csv(csv.DictReader(out))


def _results(outcome):
    """process_csv returns {'records': [row dicts with RESULT], ...}."""
    return outcome['records']


@override_settings(MULTI_CAMPUS=False)
class CsvImportWritesLinkCodeTests(TestCase):
    def setUp(self):
        self.campus = _campus()

    def test_update_writes_the_row_code_to_the_link(self):
        hs = _hs(sau='OLD1', name='Imported')
        _import([{'name': 'Imported', 'code': hs.code, 'sau': 'NEW1'}])
        self.assertEqual(_link_code(hs), 'NEW1')

    def test_create_seeds_the_link_code(self):
        _import([{'name': 'Brand New', 'code': 'bn-001', 'sau': 'NEW2'}])
        self.assertEqual(_link_code(HighSchool.objects.get(code='bn-001')), 'NEW2')

    def test_blank_cell_does_not_clear_the_link_code(self):
        hs = _hs(sau='KEEP1', name='Keeper')
        _import([{'name': 'Keeper', 'code': hs.code, 'sau': ''}])
        self.assertEqual(_link_code(hs), 'KEEP1')

    def test_code_clash_leaves_link_unchanged_and_says_so(self):
        _hs(sau='TAKEN', name='Holder')
        hs = _hs(sau='MINE', name='Mover')
        outcome = _import([{'name': 'Mover', 'code': hs.code, 'sau': 'TAKEN'}])
        self.assertEqual(_link_code(hs), 'MINE')
        result = [r for r in _results(outcome) if r.get('code') == hs.code][0]
        self.assertIn('TAKEN', result['RESULT'])
        self.assertIn('Holder', result['RESULT'])
