"""Campus scoping helpers for high schools."""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from cis.campus_context import campus_context
from cis.highschool_scope import (
    campus_highschools, highschool_for_building_code, picker_queryset,
    scope_highschools)
from cis.models.course import Campus
from cis.models.highschool import HighSchool, HighSchoolCampus


def _campus():
    return Campus.objects.create(
        name=f'C-{uuid.uuid4().hex[:8]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}_{uuid.uuid4().hex[:6]}')


def _hs(name, **kw):
    kw.setdefault('code', uuid.uuid4().hex[:8])
    hs = HighSchool.objects.create(name=name, **kw)
    # The new-school signal may auto-link; these tests set links explicitly.
    HighSchoolCampus.objects.filter(highschool=hs).delete()
    return hs


def _link(hs, campus, code='', status='Active'):
    return HighSchoolCampus.objects.create(
        highschool=hs, campus=campus, building_code=code, status=status)


class _Base(TestCase):
    def setUp(self):
        self.a, self.b = _campus(), _campus()
        self.active = _hs('Alpha')
        self.inactive = _hs('Bravo')
        self.other = _hs('Charlie')
        self.unlinked = _hs('Delta')
        _link(self.active, self.a, 'AA')
        _link(self.inactive, self.a, 'BB', 'Inactive')
        _link(self.other, self.b, 'CC')


@override_settings(MULTI_CAMPUS=True)
class MultiCampusTests(_Base):
    def test_campus_highschools_active_only(self):
        self.assertEqual(list(campus_highschools(self.a)), [self.active])

    def test_campus_highschools_uses_context(self):
        with campus_context(self.b):
            self.assertEqual(list(campus_highschools()), [self.other])

    def test_no_campus_fails_closed(self):
        self.assertEqual(campus_highschools().count(), 0)
        qs = HighSchool.objects.all()
        self.assertEqual(scope_highschools(qs).count(), 0)

    def test_scope_includes_any_status(self):
        qs = scope_highschools(HighSchool.objects.all(), self.a)
        self.assertEqual({h.pk for h in qs}, {self.active.pk, self.inactive.pk})

    def test_scope_uses_context(self):
        with campus_context(self.b):
            qs = scope_highschools(HighSchool.objects.all())
        self.assertEqual(list(qs), [self.other])

    def test_scope_superuser_unchanged(self):
        su = get_user_model()(username='su', is_superuser=True)
        qs = HighSchool.objects.all()
        self.assertIs(scope_highschools(qs, user=su), qs)

    def test_picker_active_only(self):
        self.assertEqual(list(picker_queryset(self.a)), [self.active])

    def test_picker_keep_instance_and_pk(self):
        for keep in (self.unlinked, self.unlinked.pk):
            names = [h.name for h in picker_queryset(self.a, keep=keep)]
            self.assertEqual(names, ['Alpha', 'Delta'])

    def test_picker_keep_already_listed_no_duplicate(self):
        self.assertEqual(
            picker_queryset(self.a, keep=self.active).count(), 1)

    def test_picker_no_campus_only_keep(self):
        self.assertEqual(picker_queryset().count(), 0)
        self.assertEqual(
            list(picker_queryset(keep=self.unlinked)), [self.unlinked])

    def test_code_match_link(self):
        self.assertEqual(highschool_for_building_code('AA', self.a), self.active)

    def test_code_inactive_link_matches(self):
        self.assertEqual(highschool_for_building_code('BB', self.a), self.inactive)

    def test_code_is_per_campus(self):
        self.assertIsNone(highschool_for_building_code('CC', self.a))

    def test_code_no_fallback_to_sau_or_code(self):
        _hs('Echo', sau='ZZ', code='YY')
        self.assertIsNone(highschool_for_building_code('ZZ', self.a))
        self.assertIsNone(highschool_for_building_code('YY', self.a))

    def test_code_no_campus_none(self):
        self.assertIsNone(highschool_for_building_code('AA'))

    def test_empty_code_none(self):
        _link(self.unlinked, self.b)
        self.assertIsNone(highschool_for_building_code('', self.b))
        self.assertIsNone(highschool_for_building_code(None, self.b))


@override_settings(MULTI_CAMPUS=False)
class SingleCampusTests(_Base):
    def setUp(self):
        super().setUp()
        # Make self.a the deployment campus (first prefixed by name).
        Campus.objects.filter(pk=self.a.pk).update(name='0000-first')
        Campus.objects.filter(pk=self.b.pk).update(name='0001-second')
        for c in Campus.objects.filter(
                code__startswith=settings.CAMPUS_CODE_PREFIX).exclude(
                pk__in=[self.a.pk, self.b.pk]):
            c.name = f'zz-{c.name}'
            c.save()

    def test_defaults_to_deployment_campus(self):
        self.assertEqual(list(campus_highschools()), [self.active])
        qs = scope_highschools(HighSchool.objects.all())
        self.assertEqual({h.pk for h in qs}, {self.active.pk, self.inactive.pk})
        self.assertEqual(list(picker_queryset()), [self.active])

    def test_code_link_match(self):
        self.assertEqual(highschool_for_building_code('BB'), self.inactive)

    def test_code_falls_back_to_sau_then_code(self):
        by_sau = _hs('Echo', sau='SAU1')
        by_code = _hs('Foxtrot', code='FC1')
        self.assertEqual(highschool_for_building_code('SAU1'), by_sau)
        self.assertEqual(highschool_for_building_code('FC1'), by_code)
        self.assertIsNone(highschool_for_building_code('nope'))

    def test_empty_code_none(self):
        self.assertIsNone(highschool_for_building_code(''))
        self.assertIsNone(highschool_for_building_code(None))
