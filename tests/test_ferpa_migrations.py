"""Migrations 0103 (legacy copy) and 0105 (campus backfill) for package-cis#65."""
import importlib

from django.apps import apps as django_apps
from django.test import TestCase

from cis.models.student import StudentFerpa
from cis.tests.test_ferpa_per_campus import FerpaFixtureMixin


class LegacyCopyTests(FerpaFixtureMixin, TestCase):
    def setUp(self):
        self.build()

    def test_legacy_campus_holds_json(self):
        # After 0104 there is no JSON `campus` to copy from; the 0103 copy and
        # its reverse are exercised end to end by the dev-DB
        # forward/back/forward run in Task 2.
        f = StudentFerpa.objects.create(
            student=self.student, campus=self.ewu, permissions_granted={},
            legacy_campus=['North'])
        self.assertEqual(StudentFerpa.objects.get(pk=f.pk).legacy_campus, ['North'])


from django.test import override_settings  # noqa: E402


class BackfillTests(FerpaFixtureMixin, TestCase):
    def setUp(self):
        self.build()
        self.m = importlib.import_module('cis.migrations.0105_studentferpa_campus_backfill')

    def _row(self, **pg):
        return StudentFerpa.objects.create(
            student=self.student, campus=None, permissions_granted=dict(pg))

    def _meta(self, **meta):
        type(self.student).objects.filter(pk=self.student.pk).update(meta=meta)

    def test_single_campus_assigns_deployment_campus_and_copies_freshness(self):
        self._meta(ferpa_completed_for=['202610'], ferpa_completed_on='09/01/2026')
        row = self._row()
        self.m.forward(django_apps, None)
        row.refresh_from_db()
        self.assertEqual(row.campus, self.ewu)
        self.assertEqual(row.completed_for, ['202610'])
        self.assertEqual(str(row.completed_on), '2026-09-01')

    def test_single_campus_bad_date_becomes_null(self):
        self._meta(ferpa_completed_for=['X'], ferpa_completed_on='soon')
        row = self._row()
        self.m.forward(django_apps, None)
        row.refresh_from_db()
        self.assertIsNone(row.completed_on)

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_matches_college_name(self):
        self._meta(ferpa_completed_for=['202610'])
        row = self._row(college_name=self.b.name)
        self.m.forward(django_apps, None)
        row.refresh_from_db()
        self.assertEqual(row.campus, self.b)
        self.assertEqual(row.completed_for, ['202610'])

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_unmatched_stays_null_without_freshness(self):
        self._meta(ferpa_completed_for=['202610'])
        row = self._row(college_name='Nowhere College')
        other = self._row()
        self.m.forward(django_apps, None)
        for r in (row, other):
            r.refresh_from_db()
            self.assertIsNone(r.campus)
            self.assertEqual(r.completed_for, [])

    def test_backward_restores_meta_and_unassigns(self):
        row = self._row()
        self.m.forward(django_apps, None)
        StudentFerpa.objects.filter(pk=row.pk).update(completed_for=['202630'])
        self._meta()
        self.m.backward(django_apps, None)
        row.refresh_from_db()
        self.student.refresh_from_db()
        self.assertIsNone(row.campus)
        self.assertEqual(self.student.meta['ferpa_completed_for'], ['202630'])
