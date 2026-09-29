"""MC-01 (#25): the campus a request, signal, command or cron job is serving.

current_campus() answers from campus_context() when one is active. Without one,
a single-campus deployment gets its campus -- so the ~50 existing tenants
behave as today -- and a multi-campus deployment raises NoCampusContext rather
than guessing. Multi-campus mode is settings.MULTI_CAMPUS only; it is never
derived from how many prefixed campuses exist.
"""
import uuid

from django.conf import settings
from django.test import TestCase, override_settings

from cis.campus_context import (
    NoCampusContext, campus_context, current_campus, current_campus_or_none,
    is_multi_campus,
)
from cis.models.course import Campus


def _campus(name):
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')


class SingleCampusTests(TestCase):
    def setUp(self):
        Campus.objects.all().delete()
        self.only = _campus('Only')

    def test_defaults_to_the_only_campus(self):
        self.assertFalse(is_multi_campus())
        self.assertEqual(current_campus(), self.only)
        self.assertEqual(current_campus_or_none(), self.only)

    def test_unprefixed_campuses_do_not_count(self):
        Campus.objects.create(name='Legacy', code=f'ZZZ-{uuid.uuid4().hex[:6]}')
        self.assertFalse(is_multi_campus())
        self.assertEqual(current_campus(), self.only)

    def test_no_campus_at_all_is_none_not_an_error(self):
        Campus.objects.all().delete()
        self.assertIsNone(current_campus())
        self.assertIsNone(current_campus_or_none())

    def test_explicit_context_still_wins(self):
        other = Campus.objects.create(name='Other', code=f'ZZZ-{uuid.uuid4().hex[:6]}')
        with campus_context(other):
            self.assertEqual(current_campus(), other)
        self.assertEqual(current_campus(), self.only)


class NotDerivedFromDataTests(TestCase):
    def test_two_prefixed_campuses_do_not_switch_modes(self):
        Campus.objects.all().delete()
        first = _campus('A')
        _campus('B')
        self.assertFalse(is_multi_campus())
        self.assertEqual(current_campus(), first)


@override_settings(MULTI_CAMPUS=True)
class MultiCampusTests(TestCase):
    def setUp(self):
        Campus.objects.all().delete()
        self.c1 = _campus('C1')
        self.c2 = _campus('C2')

    def test_enabled_by_the_setting(self):
        self.assertTrue(is_multi_campus())

    def test_unset_raises(self):
        with self.assertRaises(NoCampusContext):
            current_campus()
        self.assertIsNone(current_campus_or_none())

    def test_context_sets_and_resets(self):
        with campus_context(self.c1):
            self.assertEqual(current_campus(), self.c1)
        with self.assertRaises(NoCampusContext):
            current_campus()

    def test_nested_contexts_restore_the_outer_campus(self):
        with campus_context(self.c1):
            with campus_context(self.c2):
                self.assertEqual(current_campus(), self.c2)
            self.assertEqual(current_campus(), self.c1)

    def test_outer_campus_restored_after_an_exception(self):
        with campus_context(self.c1):
            with self.assertRaises(ValueError):
                with campus_context(self.c2):
                    raise ValueError('boom')
            self.assertEqual(current_campus(), self.c1)
        self.assertIsNone(current_campus_or_none())


class ExplicitSettingTests(TestCase):
    def setUp(self):
        Campus.objects.all().delete()
        self.only = _campus('Only')

    @override_settings(MULTI_CAMPUS=True)
    def test_setting_forces_multi_campus_mode(self):
        self.assertTrue(is_multi_campus())
        with self.assertRaises(NoCampusContext):
            current_campus()

    @override_settings(MULTI_CAMPUS=False)
    def test_setting_forces_single_campus_mode(self):
        _campus('Second')
        self.assertFalse(is_multi_campus())
        self.assertIsNotNone(current_campus())
