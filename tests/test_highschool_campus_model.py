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
    return HighSchool.objects.create(name=name, code=uuid.uuid4().hex[:8], **kw)


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

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_links_nothing(self):
        self._single_campus()
        _hs('X', sau='BH')
        backfill.forward(real_apps, None)
        self.assertEqual(HighSchoolCampus.objects.count(), 0)

    @override_settings(MULTI_CAMPUS=False)
    def test_several_prefixed_campuses_links_nothing(self):
        self._single_campus()
        _campus()
        _hs('X')
        backfill.forward(real_apps, None)
        self.assertEqual(HighSchoolCampus.objects.count(), 0)
