"""`duplicate` is a real registration status.

A counselor reviewing recommendations needs a third outcome besides Approved
and Not Approved: a student who entered the same registration twice. Recording
that as a denial misreports the school's approval rate. HVCC has carried the
status in its own tree for some time
(`Canusia/hvcc`, `webapp/cis/models/section.py`); this brings it into the
package so the portal package can offer the option without every tenant
patching `cis`. See ewu#47.
"""
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models import CustomUser
from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.term import AcademicYear, Term


class DuplicateRegistrationStatusTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})

        u = CustomUser.objects.create_user(
            username='dup', email='dup@example.com', password='x')
        hs = HighSchool.objects.create(name='HS Dup')
        self.student = Student.objects.create(user=u, highschool=hs)

        ay = AcademicYear.objects.create(name='AY Dup')
        term = Term.objects.create(academic_year=ay, code='F27', label='Fall 27')
        cohort = Cohort.objects.create(name='Cohort Dup', designator='CD')
        course = Course.objects.create(
            catalog_number='101', title='Intro', name='COURSE DUP',
            cohort=cohort, credit_hours=3)
        self.section = ClassSection.objects.create(
            term=term, course=course, class_number='CN-DUP',
            section_number='01', highschool=hs)

    def test_duplicate_is_an_offered_status(self):
        self.assertIn('duplicate', dict(StudentRegistration.STATUS_OPTIONS))

    def test_a_registration_can_be_saved_as_duplicate(self):
        """full_clean() validates against the field's choices, so this is what
        would reject the value if it were only added to a template."""
        registration = StudentRegistration(
            student=self.student, class_section=self.section,
            status='duplicate', status_changed_on={})

        # `pay_type` and `status_changed_on` default to values Django counts as
        # blank; neither is under test here.
        registration.full_clean(
            exclude=['highschool', 'pay_type', 'status_changed_on'])
        registration.save()

        registration.refresh_from_db()
        self.assertEqual(registration.status, 'duplicate')

    def test_duplicate_is_distinct_from_not_approved(self):
        """The whole point: it must not collapse into a denial, which is what
        it would have to be recorded as today."""
        self.assertNotEqual(
            dict(StudentRegistration.STATUS_OPTIONS)['duplicate'],
            dict(StudentRegistration.STATUS_OPTIONS)['not_approved'])
