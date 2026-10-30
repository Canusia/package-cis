"""Reminders and recommendation coverage read the section's own term tree.

`ClassSection.registration_term` is being retired: a section has one `term`, and
that term's `parent` stands in for the registration term. On a tenant whose
registration-terms setting lists sub-terms [A, B] while the sections on those
sub-terms carry registration_term=P (the pre_save default), the old
`registration_term__in=` filters matched nothing.
"""
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from cis.models.course import Course, Cohort
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student, StudentRecommendation
from cis.models.term import AcademicYear, Term


class RegistrationTermReaderBase(TestCase):
    def setUp(self):
        # Test the cis defaults, not a tenant override.
        override = patch(
            'cis.models.section._tenant_registration_override', return_value=None)
        override.start()
        self.addCleanup(override.stop)

        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@localhost'})
        ay = AcademicYear.objects.create(name='2025-2026')
        self.parent = Term.objects.create(label='AY 25', code='AY25', academic_year=ay)
        self.a = Term.objects.create(
            label='Fall A', code='FAA', academic_year=ay, parent=self.parent)
        self.b = Term.objects.create(
            label='Fall B', code='FAB', academic_year=ay, parent=self.parent)
        self.hs = HighSchool.objects.create(name='Lincoln High', status='Active')
        cohort = Cohort.objects.create(name='English', designator='ENGL')
        course = Course.objects.create(
            name='ENGL& 101', title='Comp I', catalog_number='101', cohort=cohort,
            status='Active', registration_eligibility=['JR*'])
        # registration_term is left to the pre_save default: the parent.
        self.section = ClassSection.objects.create(
            course=course, term=self.a, highschool=self.hs,
            class_number='C00001', section_number='01')
        self.assertEqual(self.section.registration_term_id, self.parent.id)
        user = CustomUser.objects.create(username='s1', email='s1@x.com')
        self.student = Student.objects.create(
            user=user, highschool=self.hs, grade_level='JR')
        self.registration = StudentRegistration.objects.create(
            student=self.student, class_section=self.section, highschool=self.hs,
            status='applied', status_changed_on={})


class CounselorReminderTests(RegistrationTermReaderBase):
    def test_counselor_reminder_selects_sub_term_class(self):
        found = StudentRegistration.objects.awaiting_recommendation(
            terms=[self.a, self.b])
        self.assertIn(self.registration.id, [r.id for r in found])

    def test_counselor_reminder_selects_parent_setting(self):
        found = StudentRegistration.objects.awaiting_recommendation(
            terms=[self.parent])
        self.assertIn(self.registration.id, [r.id for r in found])

    def test_other_term_is_not_selected(self):
        other = Term.objects.create(
            label='Spring', code='SP26', academic_year=self.a.academic_year)
        found = StudentRegistration.objects.awaiting_recommendation(terms=[other])
        self.assertEqual(list(found), [])


class MissingPaymentReminderTests(RegistrationTermReaderBase):
    def _run(self, terms):
        Student.objects.filter(pk=self.student.pk).update(current_student_balance=50)
        sent = []
        with patch('cis.utils.is_student_billpay_open', return_value=True), \
                patch('cis.utils.registration_terms', return_value=terms), \
                patch('cis.utils.active_term', return_value=self.a), \
                patch.object(Student, 'send_payment_url',
                             lambda s, term_id, mode: sent.append(s.pk)), \
                patch.object(Student, 'add_note', lambda *a, **k: None):
            call_command('send_missing_payment_reminder', stdout=StringIO())
        return sent

    def test_missing_payment_reminder_finds_student(self):
        self.assertEqual(self._run(Term.objects.filter(pk__in=[self.a.pk, self.b.pk])),
                         [self.student.pk])

    def test_no_registration_terms_configured(self):
        self.assertEqual(self._run(None), [])


class RecommendationCoverageTests(RegistrationTermReaderBase):
    def _rec(self, term):
        return StudentRecommendation.objects.create(
            student=self.student, term=term, recommendation={})

    def _both_ways(self):
        from cis.views.eager import annotate_registration_flags
        regs = StudentRegistration.objects.filter(pk=self.registration.pk)
        fresh = StudentRegistration.objects.get(pk=self.registration.pk)
        annotated = [r._has_recommendation for r in annotate_registration_flags(regs)]
        return fresh.has_recommendation(), annotated

    def test_no_recommendation_is_false(self):
        self.assertEqual(self._both_ways(), (False, [False]))

    def test_rec_on_parent_covers_sub_term_registration(self):
        self._rec(self.parent)
        self.assertEqual(self._both_ways(), (True, [True]))

    def test_rec_on_sub_term_covers_registration(self):
        self._rec(self.a)
        self.assertEqual(self._both_ways(), (True, [True]))

    def test_rec_on_sibling_sub_term_does_not_cover(self):
        self._rec(self.b)
        self.assertEqual(self._both_ways(), (False, [False]))
