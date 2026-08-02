from django.test import TestCase
from django.contrib.auth.models import Group

from cis.models.customuser import CustomUser
from cis.models.term import Term, AcademicYear
from cis.models.highschool import HighSchool
from cis.models.course import Course, Cohort
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.reports.class_roster import class_roster


class ClassRosterDatasourceTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        # Signal add_note() falls back to username='cron' when no request user
        CustomUser.objects.get_or_create(username='cron', defaults={'email': 'cron@localhost'})
        self.ay = AcademicYear.objects.create(name='2025-2026')
        self.term = Term.objects.create(label='Fall 2025', code='FA25',
                                        academic_year=self.ay)
        self.hs = HighSchool.objects.create(name='Lincoln High', status='Active')
        cohort = Cohort.objects.create(name='English', designator='ENGL')
        self.course = Course.objects.create(
            name='ENGL& 101', title='Comp I', catalog_number='101',
            cohort=cohort, status='Active')
        self.section = ClassSection.objects.create(
            course=self.course, term=self.term, highschool=self.hs,
            class_number='12345', section_number='01')
        u = CustomUser.objects.create(username='s1', email='s1@x.com',
                                      first_name='Pat', last_name='Lee')
        self.student = Student.objects.create(user=u, highschool=self.hs)
        StudentRegistration.objects.create(
            student=self.student, class_section=self.section,
            highschool=self.hs, status='registered', grade='A',
            status_changed_on={})

    def _data(self):
        return {'term': [str(self.term.id)], 'highschool': [str(self.hs.id)]}

    def test_recipient_columns_include_roster_shortcodes(self):
        tokens = set(class_roster().recipient_columns().values())
        for token in ('FirstName', 'LastName', 'email', 'CRN', 'Course',
                      'Term', 'Grade', 'Status'):
            self.assertIn(token, tokens)

    def test_get_recipients_carry_field_values(self):
        rows = class_roster().get_recipients(self._data())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['FirstName'], 'Pat')
        self.assertEqual(row['email'], ['s1@x.com'])
        self.assertEqual(row['CRN'], '12345')
        self.assertEqual(row['Course'], 'ENGL& 101')
        self.assertEqual(row['Grade'], 'A')

    def test_status_filter_applies(self):
        rows = class_roster().get_recipients(
            {**self._data(), 'registration_status': ['enrolled']})
        self.assertEqual(rows, [])   # only a 'registered' row exists
