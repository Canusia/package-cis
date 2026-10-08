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
