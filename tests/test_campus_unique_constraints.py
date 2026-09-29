"""MC-08 (#32): names are unique per campus, not per deployment.

Two colleges on one multi-campus deployment can each have an academic year
called "2026-2027", a "College of Arts" and an "English / ENGL" cohort. Rows
with no campus keep today's deployment-wide uniqueness (partial constraints,
as DocumentType uses), since a plain unique_together would let NULL-campus
rows duplicate freely.
"""
import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase

from cis.models.course import Campus, Cohort, College, Department
from cis.models.term import AcademicYear


def _campus():
    return Campus.objects.create(name=f'C-{uuid.uuid4().hex[:6]}', code=f'C-{uuid.uuid4().hex[:6]}')


class PerCampusUniquenessTests(TestCase):
    def setUp(self):
        self.c1 = _campus()
        self.c2 = _campus()

    def _refused(self, factory):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                factory()

    def test_academic_year(self):
        AcademicYear.objects.create(name='2026-2027', campus=self.c1)
        AcademicYear.objects.create(name='2026-2027', campus=self.c2)
        self._refused(lambda: AcademicYear.objects.create(name='2026-2027', campus=self.c1))

    def test_academic_year_without_campus_stays_deployment_unique(self):
        AcademicYear.objects.create(name='2030-2031')
        self._refused(lambda: AcademicYear.objects.create(name='2030-2031'))

    def test_college(self):
        College.objects.create(name='College of Arts', campus=self.c1)
        College.objects.create(name='College of Arts', campus=self.c2)
        self._refused(lambda: College.objects.create(name='College of Arts', campus=self.c1))

    def test_college_without_campus_stays_deployment_unique(self):
        College.objects.create(name='Shared College')
        self._refused(lambda: College.objects.create(name='Shared College'))

    def test_department_name_is_unique_within_a_college_only(self):
        arts_1 = College.objects.create(name='Arts', campus=self.c1)
        arts_2 = College.objects.create(name='Arts', campus=self.c2)
        Department.objects.create(name='English', college=arts_1)
        Department.objects.create(name='English', college=arts_2)
        self._refused(lambda: Department.objects.create(name='English', college=arts_1))

    def test_cohort(self):
        Cohort.objects.create(name='English', designator='ENGL', campus=self.c1)
        Cohort.objects.create(name='English', designator='ENGL', campus=self.c2)
        self._refused(lambda: Cohort.objects.create(
            name='English', designator='ENGL', campus=self.c1))

    def test_cohort_without_campus_stays_deployment_unique(self):
        Cohort.objects.create(name='Math', designator='MATH')
        self._refused(lambda: Cohort.objects.create(name='Math', designator='MATH'))
