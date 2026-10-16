"""class_export has a Grade Status column right after Roster Status, labelled
like the CE Grades tab (Not Started / Draft / Submitted). (package-cis#76)
"""
import csv
import io
import uuid
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models.course import Campus, Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection
from cis.models.term import AcademicYear, Term
from cis.reports.class_export import class_export, grade_status_label

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class GradeStatusLabelTests(TestCase):
    def test_labels(self):
        self.assertEqual(grade_status_label(''), 'Not Started')
        self.assertEqual(grade_status_label(None), 'Not Started')
        self.assertEqual(grade_status_label('saved'), 'Draft')
        self.assertEqual(grade_status_label('submitted'), 'Submitted')


class ClassExportGradeStatusColumnTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@x.com'})

        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.term = Term.objects.create(
            academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.campus = Campus.objects.create(
            name=f'C-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        course = Course.objects.create(
            catalog_number='101', title='T', cohort=cohort, campus=self.campus)
        self.highschool = HighSchool.objects.create(name=f'HS-{_sfx()}')
        self.draft = ClassSection.objects.create(
            class_number='2001', term=self.term, course=course,
            highschool=self.highschool, grade_status='saved')
        self.unset = ClassSection.objects.create(
            class_number='2002', term=self.term, course=course,
            highschool=self.highschool, grade_status=None)
        self.superuser = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')

    def _run(self):
        saved = {}

        def _save(path, content):
            saved['csv'] = content.read().decode('utf-8')
            return path

        storage = mock.Mock()
        storage.save.side_effect = _save
        storage.url.side_effect = lambda p: p
        task = SimpleNamespace(id=uuid.uuid4(), created_by=self.superuser)
        data = {
            'term': [str(self.term.id)],
            'highschool': [self.highschool],
            'campus': [str(self.campus.id)],
        }
        with mock.patch('cis.reports.class_export.PrivateMediaStorage',
                        return_value=storage):
            class_export().run(task, data)
        return list(csv.reader(io.StringIO(saved['csv'])))

    def test_header_has_grade_status_right_after_roster_status(self):
        header = self._run()[0]
        self.assertIn('Grade Status', header)
        self.assertEqual(
            header.index('Grade Status'), header.index('Roster Status') + 1)

    def test_rows_carry_tab_labels_in_the_header_position(self):
        rows = self._run()
        header, body = rows[0], rows[1:]
        id_col = header.index('ID')
        col = header.index('Grade Status')
        by_id = {r[id_col]: r for r in body}
        # Every row is as wide as the header, so later columns didn't shift.
        for r in body:
            self.assertEqual(len(r), len(header))
        self.assertEqual(by_id[str(self.draft.pk)][col], 'Draft')
        self.assertEqual(by_id[str(self.unset.pk)][col], 'Not Started')
