"""`has_recommendation` must survive an unconfigured registration-terms setting.

`cis.utils.registration_terms()` returns None — not an empty queryset — when the
`<prefix>_cis_registrations` Setting row is absent, and
`StudentRecommendation.has_recommendation(student)` iterated that result
directly. Every deployment that had not configured registration terms yet raised
`TypeError: 'NoneType' object is not iterable` from
`Student.needs_recommendation()`, which the student portal and the
student-transactions signal both call.

Tenant-agnostic: it asserts a crash does not happen, not which grades or terms a
tenant configures, so it belongs in cis.tests rather than a tenant app.
"""
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.settings import Setting
from cis.models.student import Student, StudentRecommendation
from cis.utils import registration_terms


class HasRecommendationWithoutRegistrationTermsTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        user = CustomUser.objects.create(username='u1', email='u1@x.com')
        self.hs = HighSchool.objects.create(name='Lincoln High', status='Active')
        self.student = Student.objects.create(
            user=user, highschool=self.hs, grade_level='JR')

    def test_the_setting_really_is_absent(self):
        """Guards the premise: if a fixture ever seeds this row, the tests below
        would pass without exercising the None path at all."""
        self.assertFalse(
            Setting.objects.filter(key__endswith='_cis_registrations').exists())
        self.assertIsNone(registration_terms())

    def test_has_recommendation_does_not_raise(self):
        self.assertTrue(
            StudentRecommendation.has_recommendation(self.student))

    def test_student_needs_recommendation_does_not_raise(self):
        """No open registration term means nothing is outstanding."""
        self.assertFalse(self.student.needs_recommendation())

    def test_explicit_term_id_is_unaffected(self):
        self.assertFalse(
            StudentRecommendation.has_recommendation(
                self.student, term_id='00000000-0000-0000-0000-000000000000'))
