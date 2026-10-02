"""High school <-> campus links: constraints and the backfill migration."""
import importlib
import uuid

from django.apps import apps as real_apps
from django.conf import settings
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from cis.models.course import Campus
from cis.models.highschool import HighSchool, HighSchoolCampus

backfill = importlib.import_module(
    'cis.migrations.0097_highschool_campus_backfill')


def _campus(tag=''):
    return Campus.objects.create(
        name=f'C-{uuid.uuid4().hex[:8]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}_{tag}{uuid.uuid4().hex[:6]}')


def _hs(name, **kw):
    hs = HighSchool.objects.create(name=name, code=uuid.uuid4().hex[:8], **kw)
    # The new-school signal may auto-link; these tests set links explicitly.
    HighSchoolCampus.objects.filter(highschool=hs).delete()
    HighSchool.objects.filter(pk=hs.pk).update(status=hs.status)  # undo derived status
    return hs


class ConstraintTests(TestCase):
    def setUp(self):
        self.a, self.b = _campus(), _campus()
        self.h1, self.h2 = _hs('One'), _hs('Two')

    def test_one_link_per_school_and_campus(self):
        HighSchoolCampus.objects.create(highschool=self.h1, campus=self.a)
        with self.assertRaises(IntegrityError), transaction.atomic():
            HighSchoolCampus.objects.create(highschool=self.h1, campus=self.a)

    def test_code_unique_per_campus(self):
        HighSchoolCampus.objects.create(
            highschool=self.h1, campus=self.a, building_code='BH')
        with self.assertRaises(IntegrityError), transaction.atomic():
            HighSchoolCampus.objects.create(
                highschool=self.h2, campus=self.a, building_code='BH')

    def test_same_code_on_two_campuses(self):
        HighSchoolCampus.objects.create(
            highschool=self.h1, campus=self.a, building_code='BH')
        HighSchoolCampus.objects.create(
            highschool=self.h2, campus=self.b, building_code='BH')
        self.assertEqual(HighSchoolCampus.objects.count(), 2)

    def test_empty_codes_repeat(self):
        HighSchoolCampus.objects.create(highschool=self.h1, campus=self.a)
        HighSchoolCampus.objects.create(highschool=self.h2, campus=self.a)
        self.assertEqual(HighSchoolCampus.objects.filter(campus=self.a).count(), 2)

    def test_defaults_relations_and_history(self):
        link = HighSchoolCampus.objects.create(highschool=self.h1, campus=self.a)
        self.assertEqual((link.building_code, link.status), ('', 'Active'))
        self.assertEqual(list(self.h1.campuses.all()), [self.a])
        self.assertEqual(list(self.a.highschools.all()), [self.h1])
        self.assertEqual(self.h1.campus_links.count(), 1)
        self.assertEqual(self.a.highschool_links.count(), 1)
        self.assertEqual(link.history.count(), 1)


class BackfillTests(TestCase):
    def setUp(self):
        HighSchool.objects.all().delete()
        HighSchoolCampus.objects.all().delete()

    def _single_campus(self):
        Campus.objects.filter(
            code__startswith=settings.CAMPUS_CODE_PREFIX).delete()
        return _campus()

    @override_settings(MULTI_CAMPUS=False)
    def test_single_campus_links_every_school(self):
        campus = self._single_campus()
        h_bh = _hs('BH', sau='BH ')
        h_dash = _hs('Dash', sau='-', status='Inactive')
        h_blank = _hs('Blank', sau='')
        h_none = _hs('None', sau=None)
        h_dup = _hs('Dup', sau='BH')
        backfill.forward(real_apps, None)
        links = {l.highschool_id: l for l in HighSchoolCampus.objects.all()}
        self.assertEqual(len(links), 5)
        self.assertTrue(all(l.campus_id == campus.id for l in links.values()))
        self.assertEqual(links[h_dash.id].status, 'Inactive')
        self.assertEqual(links[h_dash.id].building_code, '')
        self.assertEqual(links[h_blank.id].building_code, '')
        self.assertEqual(links[h_none.id].building_code, '')
        codes = sorted([links[h_bh.id].building_code, links[h_dup.id].building_code])
        self.assertEqual(codes, ['', 'BH'])

    @override_settings(MULTI_CAMPUS=False)
    def test_overlong_sau_gets_empty_code(self):
        self._single_campus()
        h = _hs('Long', sau='X' * 25)
        backfill.forward(real_apps, None)
        self.assertEqual(
            HighSchoolCampus.objects.get(highschool=h).building_code, '')

    @override_settings(MULTI_CAMPUS=False)
    def test_status_mapped_explicitly(self):
        self._single_campus()
        want = {'Active': 'Active', '': 'Inactive', 'Pending': 'Inactive',
                'Inactive': 'Inactive'}
        schools = {s: _hs(f'S-{i}', status=s) for i, s in enumerate(want)}
        backfill.forward(real_apps, None)
        for s, h in schools.items():
            self.assertEqual(
                HighSchoolCampus.objects.get(highschool=h).status, want[s], s)

    @override_settings(MULTI_CAMPUS=False)
    def test_status_case_insensitive_without_logging(self):
        self._single_campus()
        a, b = _hs('Lower', status='active'), _hs('Upper', status=' ACTIVE ')
        with self.assertNoLogs(backfill.logger, level='WARNING'):
            backfill.forward(real_apps, None)
        for h in (a, b):
            self.assertEqual(
                HighSchoolCampus.objects.get(highschool=h).status, 'Active')

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_links_nothing(self):
        self._single_campus()
        _hs('X', sau='BH')
        backfill.forward(real_apps, None)
        self.assertEqual(HighSchoolCampus.objects.count(), 0)

    @override_settings(MULTI_CAMPUS=False)
    def test_several_prefixed_campuses_link_to_first_by_name(self):
        # Same rule as cis.campus_context.deployment_campus().
        first = self._single_campus()
        Campus.objects.filter(pk=first.pk).update(name='0000-first')
        _campus()
        h1, h2 = _hs('X'), _hs('Y', status='Inactive')
        backfill.forward(real_apps, None)
        self.assertEqual(
            sorted(HighSchoolCampus.objects.values_list('highschool_id', 'campus_id')),
            sorted([(h1.pk, first.pk), (h2.pk, first.pk)]))

    @override_settings(MULTI_CAMPUS=False)
    def test_no_prefixed_campus_links_nothing(self):
        Campus.objects.filter(
            code__startswith=settings.CAMPUS_CODE_PREFIX).delete()
        _hs('X')
        backfill.forward(real_apps, None)
        self.assertEqual(HighSchoolCampus.objects.count(), 0)

    @override_settings(MULTI_CAMPUS=False)
    def test_school_status_written_as_derived(self):
        self._single_campus()
        want = {'active': 'Active', ' ACTIVE ': 'Active', 'Pending': 'Inactive',
                '': 'Inactive', 'Inactive': 'Inactive'}
        schools = {s: _hs(f'S-{i}', status=s) for i, s in enumerate(want)}
        # Historical models, as in a real migrate: no link signals fire, so
        # the migration itself must write the derived status.
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        state = MigrationExecutor(connection).loader.project_state(
            ('cis', '0097_highschool_campus_backfill'))
        backfill.forward(state.apps, None)
        for s, h in schools.items():
            self.assertEqual(HighSchool.objects.get(pk=h.pk).status, want[s], repr(s))
