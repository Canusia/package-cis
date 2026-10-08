"""Recommendation, parent consent and agreement checks per campus (package-cis#66).

Spec: docs/superpowers/specs/2026-10-08-recommendations-per-campus-design.md
"""
import uuid

from django.conf import settings
from django.test import TestCase, override_settings

from cis.campus_context import campus_context
from cis.models import CustomUser
from cis.models.course import Campus, Cohort, Course
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import (
    ParentConsent, Student, StudentAgreement, StudentRecommendation)
from cis.models.term import AcademicYear, Term

REG_KEY = f'{settings.CAMPUS_CODE_PREFIX}_cis_registrations'


class ConsentFixture:
    def build(self):
        p = settings.CAMPUS_CODE_PREFIX
        sfx = uuid.uuid4().hex[:6]
        self.a = Campus.objects.create(name=f'A {sfx}', code=f'{p}_A{sfx}')
        self.b = Campus.objects.create(name=f'B {sfx}', code=f'{p}_B{sfx}')
        from django.contrib.auth.models import Group
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        user = CustomUser.objects.create_user(username=f's{sfx}', email=f's{sfx}@x.com', password='x')
        self.student = Student.objects.create(user=user)
        self.cohort = Cohort.objects.create(name=f'C{sfx}', designator=f'D{sfx[:4]}')

    def term(self, campus, code):
        ay = AcademicYear.objects.create(name=f'AY{uuid.uuid4().hex[:6]}', campus=campus)
        return Term.objects.create(academic_year=ay, code=code, label=code)

    def open_terms(self, campus, *terms):
        Setting.objects.update_or_create(key=REG_KEY, campus=campus, defaults={'value': {
            'registration_terms': [str(t.id) for t in terms], 'active_term': str(terms[0].id),
            'signature_term': str(terms[0].id)}})

    def register(self, campus, term):
        from contextlib import nullcontext
        # Multi-campus saves need a campus context (cis/signals/campus.py).
        with (campus_context(campus) if campus is not None else nullcontext()):
            course = Course.objects.create(catalog_number=uuid.uuid4().hex[:4], title='T',
                                           name=f'ENG {uuid.uuid4().hex[:4]}', cohort=self.cohort,
                                           campus=campus)
            section = ClassSection.objects.create(course=course, term=term,
                                                  class_number=uuid.uuid4().hex[:6],
                                                  section_number='001')
            return StudentRegistration.objects.create(
                student=self.student, class_section=section, status='applied',
                status_changed_on={})


@override_settings(MULTI_CAMPUS=True)
class MultiCampusConsentTests(ConsentFixture, TestCase):
    def setUp(self):
        self.build()
        self.ta, self.tb = self.term(self.a, '202610'), self.term(self.b, '202610')
        self.open_terms(self.a, self.ta)
        self.open_terms(self.b, self.tb)
        self.register(self.a, self.ta)
        self.register(self.b, self.tb)

    def test_recommendation_reporting_covers_every_campus(self):
        StudentRecommendation.objects.create(student=self.student, term=self.ta, recommendation={})
        self.assertFalse(StudentRecommendation.has_recommendation(self.student))
        with campus_context(self.a):
            self.assertFalse(StudentRecommendation.has_recommendation(self.student))
            self.assertTrue(self.student.has_recommendation())
        with campus_context(self.b):
            self.assertFalse(self.student.has_recommendation())
        StudentRecommendation.objects.create(student=self.student, term=self.tb, recommendation={})
        self.assertTrue(StudentRecommendation.has_recommendation(self.student))

    def test_parent_consent_same_matrix(self):
        with campus_context(self.a):   # its post_save signal reads campus settings
            ParentConsent.objects.create(student=self.student, term=self.ta, parent_signature='x')
        self.assertFalse(ParentConsent.has_signed(self.student))
        with campus_context(self.a):
            self.assertTrue(self.student.has_signed_parent_consent())
        with campus_context(self.b):
            self.assertFalse(self.student.has_signed_parent_consent())

    def test_agreement_same_matrix(self):
        StudentAgreement.objects.create(student=self.student, term=self.ta, student_signature='x')
        self.assertFalse(StudentAgreement.has_signed(self.student))
        with campus_context(self.a):
            self.assertTrue(self.student.has_signed_student_agreement())
        with campus_context(self.b):
            self.assertFalse(self.student.has_signed_student_agreement())

    def test_explicit_campus(self):
        StudentAgreement.objects.create(student=self.student, term=self.ta, student_signature='x')
        self.assertTrue(StudentAgreement.has_signed(self.student, campus=self.a))
        self.assertFalse(StudentAgreement.has_signed(self.student, campus=self.b))

    def test_default_term_per_campus(self):
        self.assertEqual(str(StudentAgreement.default_term(campus=self.b)), str(self.tb.id))
        self.assertEqual(str(StudentRecommendation.default_term(campus=self.a)), str(self.ta.id))


@override_settings(MULTI_CAMPUS=True)
class UnregisteredCampusTests(ConsentFixture, TestCase):
    def setUp(self):
        self.build()
        self.ta, self.tb = self.term(self.a, 'A1'), self.term(self.b, 'B1')
        self.open_terms(self.a, self.ta)
        self.open_terms(self.b, self.tb)
        self.register(self.a, self.ta)
        StudentAgreement.objects.create(student=self.student, term=self.ta, student_signature='x')

    def test_reporting_ignores_campuses_without_registrations(self):
        self.assertTrue(StudentAgreement.has_signed(self.student))

    def test_portal_on_b_asks_for_bs_agreement(self):
        with campus_context(self.b):
            self.assertFalse(self.student.has_signed_student_agreement())

    def test_no_context_no_registrations_is_not_outstanding(self):
        StudentRegistration.objects.filter(student=self.student).delete()
        self.assertTrue(StudentRecommendation.has_recommendation(self.student))
        self.assertTrue(ParentConsent.has_signed(self.student))


class SingleCampusConsentTests(ConsentFixture, TestCase):
    def setUp(self):
        self.build()
        self.t = self.term(None, '202610')
        self.open_terms(None, self.t)
        self.register(None, self.t)

    def test_unchanged_single_campus(self):
        self.assertFalse(StudentRecommendation.has_recommendation(self.student))
        StudentRecommendation.objects.create(student=self.student, term=self.t, recommendation={})
        self.assertTrue(self.student.has_recommendation())

    def test_registration_terms_absent_means_nothing_open(self):
        Setting.objects.filter(key=REG_KEY).delete()
        self.assertTrue(StudentRecommendation.has_recommendation(self.student))
        self.assertTrue(ParentConsent.has_signed(self.student))
        self.assertTrue(StudentAgreement.has_signed(self.student))
