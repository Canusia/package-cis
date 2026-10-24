"""Instructor and high-school importer tenant knobs (package-cis#114 item 10).

Knobs come from the tenant's `instructor_import` / `highschool_import`
service modules and default to the package behaviour.
"""
import datetime
import uuid
from typing import Optional
from unittest import mock

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from pydantic import Field, field_validator

from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher
from cis.services.importers.highschool_importer import HighSchoolImporter
from cis.services.importers.highschool_schema import HighSchoolRow, highschool_row_schema
from cis.services.importers.instructor_importer import InstructorImporter
from cis.services.importers.validation import coerce_yes_no
from cis.tests.fake_tenant.services import highschool_import, instructor_import

FAKE_TENANT = 'cis.tests.fake_tenant'

NNU_STYLE_FIELDS = (
    'first_name', 'last_name', 'middle_name', 'secondary_email', 'alt_email',
    'address1', 'city', 'state', 'postal_code', 'primary_phone',
    'secondary_phone', 'date_of_birth',
)


def _sfx():
    return uuid.uuid4().hex[:6]


@override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
class InstructorUpdateFieldsTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='instructor')
        self.hs = HighSchool.objects.create(name='Liberty High', code=_sfx())
        cohort, _ = Cohort.objects.get_or_create(designator='PHED', defaults={'name': 'PHED'})
        Course.objects.create(name='PHED 150', catalog_number='150', title='PE', cohort=cohort)
        InstructorImporter().process_csv(iter([self._row()]))
        self.teacher = Teacher.objects.get(user__psid='01064335')

    def _row(self, **overrides):
        row = {
            'teacherid': '01064335', 'teacher_id': 'wabell',
            'last_name': 'Abell', 'first_name': 'Whitney', 'middle_name': '',
            'highschool_ceeb': self.hs.code,
            'secondary_email': 'wabell@ewu.edu', 'primary_email': 'wabell@cvsd.org',
            'home_email': '', 'status': 'Active',
            'home_address': '1 Main', 'home_city': 'Liberty Lake',
            'home_state': 'WA', 'home_zip': '99019',
            'cell_phone': '5095583868', 'home_phone': '',
            'date_of_birth': '03/15/1988', 'date_of_hire': '03/18/2025',
            'orientation_date': '08/11/2025', 'course_1': 'PHED 150',
        }
        row.update(overrides)
        return row

    def _changed_row(self):
        return self._row(first_name='Whit', home_city='Spokane', home_address='',
                         date_of_birth='04/16/1989', status='Inactive',
                         teacher_id='newlogin', primary_email='new@cvsd.org',
                         orientation_date='09/01/2026')

    def test_default_reuses_without_updating(self):
        result = InstructorImporter().process_csv(iter([self._changed_row()]))
        self.assertEqual(result['summary']['successful'], 1)
        user = Teacher.objects.get(pk=self.teacher.pk).user
        self.assertEqual((user.first_name, user.city), ('Whitney', 'Liberty Lake'))

    def test_updates_listed_fields_skipping_blanks(self):
        with mock.patch.object(instructor_import, 'INSTRUCTOR_IMPORT_UPDATE_FIELDS',
                               NNU_STYLE_FIELDS, create=True):
            InstructorImporter().process_csv(iter([self._changed_row()]))
        teacher = Teacher.objects.get(pk=self.teacher.pk)
        user = teacher.user
        self.assertEqual(user.first_name, 'Whit')
        self.assertEqual(user.city, 'Spokane')
        self.assertEqual(user.address1, '1 Main')  # blank cell skipped
        self.assertEqual(user.date_of_birth, datetime.date(1989, 4, 16))
        # Identity and program state are never touched.
        self.assertEqual((user.username, user.email, user.psid),
                         ('wabell', 'wabell@cvsd.org', '01064335'))
        self.assertEqual(teacher.status, 'Active')
        self.assertEqual(teacher.orientation_date, datetime.date(2025, 8, 11))

    def test_protected_and_unknown_names_are_ignored(self):
        with mock.patch.object(instructor_import, 'INSTRUCTOR_IMPORT_UPDATE_FIELDS',
                               ('email', 'username', 'psid', 'no_such_field', 'city'),
                               create=True):
            importer = InstructorImporter()
            self.assertEqual(importer.update_fields, [('city', 'home_city')])
            importer.process_csv(iter([self._changed_row()]))
        user = Teacher.objects.get(pk=self.teacher.pk).user
        self.assertEqual((user.email, user.username, user.city),
                         ('wabell@cvsd.org', 'wabell', 'Spokane'))


class CteRow(HighSchoolRow):
    """A tenant schema with an invented Y/N column, mapped onto is_cte."""
    career_tech: Optional[bool] = Field(
        default=None, description="Career/technical school (Y/N)",
        json_schema_extra={"db_field": "is_cte"})

    @field_validator('career_tech', mode='before')
    @classmethod
    def yes_no(cls, v):
        return coerce_yes_no(v)


@override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
class HighSchoolRowSchemaTests(TestCase):
    def setUp(self):
        self.code = _sfx()

    def _import(self, **row):
        row = dict({'name': 'Liberty High', 'code': self.code}, **row)
        return HighSchoolImporter().process_csv(iter([row]))

    def _schema(self, schema):
        return mock.patch.object(highschool_import, 'ROW_SCHEMA', schema, create=True)

    def _extra(self, fields):
        return mock.patch.object(highschool_import, 'EXTRA_UPDATE_FIELDS', fields, create=True)

    def test_default_schema(self):
        self.assertIs(highschool_row_schema(), HighSchoolRow)
        self._import(career_tech='Y')
        self.assertFalse(HighSchool.objects.get(code=self.code).is_cte)

    def test_schema_column_on_create(self):
        with self._schema(CteRow):
            self.assertIn('career_tech', highschool_row_schema().csv_headers())
            result = self._import(career_tech='yes')
        self.assertEqual(result['summary']['successful'], 1)
        self.assertTrue(HighSchool.objects.get(code=self.code).is_cte)

    def test_bad_yes_no_fails_the_row(self):
        with self._schema(CteRow):
            result = self._import(career_tech='maybe')
        self.assertEqual(result['summary']['failed'], 1)

    def test_schema_column_is_create_only_without_extra_update_fields(self):
        with self._schema(CteRow):
            self._import(career_tech='N')
            self._import(career_tech='Y', city='Spokane')
        hs = HighSchool.objects.get(code=self.code)
        self.assertFalse(hs.is_cte)
        self.assertEqual(hs.city, 'Spokane')

    def test_extra_update_fields_update_existing_schools(self):
        for bulk in (True, False):
            code = _sfx()
            with self._schema(CteRow), self._extra(('is_cte',)):
                for flag in ('N', 'Y'):
                    HighSchoolImporter(use_bulk_operations=bulk).process_csv(
                        iter([{'name': 'Liberty High', 'code': code, 'career_tech': flag}]))
            self.assertTrue(HighSchool.objects.get(code=code).is_cte, bulk)
