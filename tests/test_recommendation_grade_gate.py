"""#10: the grade-level recommendation gate is a setting.

`require_grade_level_match` on the counselor_recommendation setting, default
on. When off, every applied registration needs a recommendation regardless of
the `*` marks in Course.registration_eligibility. All five call sites must
agree: the three Python ones (StudentRegistration.needs_recommendation,
get_pending_recommendations, Student.needs_recommendation) and the two built
on recommendation_required_q() (awaiting_recommendation, the CE
missing_recommendation report).
"""
from unittest import mock

from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from cis.models.course import Cohort, Course
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import (
    Student, recommendation_grade_gate_enabled, recommendation_required_q,
)
from cis.models.term import AcademicYear, Term
from cis.settings.counselor_recommendation import counselor_recommendation


class RecommendationGradeGateTests(TestCase):
    """The stock cis behaviour. Tenant overrides are switched off here: ewu,
    lsco and tvcc override needs_recommendation and friends with their own
    grade check, and an override deliberately wins over the setting."""

    def setUp(self):
        patcher = mock.patch(
            'cis.services.tenant_services.get_tenant_override', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@localhost'})
        ay = AcademicYear.objects.create(name='2025-2026')
        term = Term.objects.create(label='Fall 2025', code='FA25', academic_year=ay)
        self.hs = HighSchool.objects.create(name='Lincoln High', status='Active')
        cohort = Cohort.objects.create(name='English', designator='ENGL')
        # Seniors need a recommendation for this course; the student is a junior.
        course = Course.objects.create(
            name='ENGL& 101', title='Comp I', catalog_number='101',
            cohort=cohort, status='Active', registration_eligibility=['SR*'])
        section = ClassSection.objects.create(
            course=course, term=term, highschool=self.hs,
            registration_term=term, class_number='C00001', section_number='01')
        user = CustomUser.objects.create(username='junior', email='junior@x.com')
        self.student = Student.objects.create(
            user=user, highschool=self.hs, grade_level='JR')
        self.reg = StudentRegistration.objects.create(
            student=self.student, class_section=section, highschool=self.hs,
            status='applied', status_changed_on={})

    def _gate(self, on):
        Setting.objects.update_or_create(
            key=counselor_recommendation.key,
            defaults={'value': {'upload_label': 'x', 'require_grade_level_match': on}})

    def _surfaces(self):
        return {
            'registration': self.reg.needs_recommendation(),
            'pending': StudentRegistration.get_pending_recommendations(
                highschool_ids=[self.hs.id]).filter(pk=self.reg.pk).exists(),
            # With a term: has_recommendation(None) answers True whenever no
            # registration terms are configured, as in a test database.
            'student': self.student.needs_recommendation(
                term_id=self.reg.class_section.registration_term_id),
            'awaiting': StudentRegistration.objects.awaiting_recommendation()
                .filter(pk=self.reg.pk).exists(),
            'required_q': StudentRegistration.objects
                .filter(recommendation_required_q(), pk=self.reg.pk).exists(),
        }

    def test_gate_defaults_on_when_setting_missing(self):
        Setting.objects.filter(key=counselor_recommendation.key).delete()
        self.assertTrue(recommendation_grade_gate_enabled())
        self.assertEqual(set(self._surfaces().values()), {False})

    def test_gate_on_skips_a_grade_without_a_star(self):
        self._gate(True)
        self.assertEqual(set(self._surfaces().values()), {False})

    def test_gate_off_requires_every_applied_registration(self):
        self._gate(False)
        self.assertFalse(recommendation_grade_gate_enabled())
        surfaces = self._surfaces()
        self.assertEqual(set(surfaces.values()), {True}, surfaces)

    def test_tenant_override_still_wins_when_gate_off(self):
        self._gate(False)
        with mock.patch('cis.models.section._tenant_registration_override',
                        return_value=lambda registration: False):
            self.assertFalse(self.reg.needs_recommendation())

    def test_missing_recommendation_report_honours_the_gate(self):
        from rest_framework.test import APIRequestFactory
        from cis.views.student import StudentViewSet
        admin = CustomUser.objects.create_superuser(
            username='su', email='su@x.com', password='x')
        admin.groups.add(Group.objects.get_or_create(name='ce')[0])

        def listed():
            request = APIRequestFactory().get('/x', {
                'record_type': 'missing_recommendation',
                'registration_term_id': str(self.reg.class_section.registration_term_id),
            })
            request.user = admin
            viewset = StudentViewSet()
            viewset.request = request
            viewset.format_kwarg = None
            return viewset.get_queryset().filter(pk=self.student.pk).exists()

        self._gate(True)
        self.assertFalse(listed())
        self._gate(False)
        self.assertTrue(listed())


class CounselorRecommendationSettingTests(TestCase):
    def _form(self, data):
        return counselor_recommendation(
            RequestFactory().get('/?report_id=x'), data)

    def test_round_trip(self):
        form = self._form({'upload_label': 'Hello'})  # unchecked box -> off
        self.assertTrue(form.is_valid(), form.errors)
        form.run_record()
        self.assertFalse(recommendation_grade_gate_enabled())

        form = self._form({'upload_label': 'Hello', 'require_grade_level_match': 'on'})
        self.assertTrue(form.is_valid(), form.errors)
        form.run_record()
        self.assertTrue(recommendation_grade_gate_enabled())

    def test_install_defaults_the_gate_on_without_touching_existing_values(self):
        Setting.objects.update_or_create(
            key=counselor_recommendation.key,
            defaults={'value': {'upload_label': 'Customised'}})
        counselor_recommendation(RequestFactory().get('/?report_id=x')).install()
        value = Setting.objects.get(key=counselor_recommendation.key).value
        self.assertEqual(value['upload_label'], 'Customised')
        self.assertIs(value['require_grade_level_match'], True)
