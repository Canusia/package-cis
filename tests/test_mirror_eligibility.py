"""Tests for the registration eligibility gate in StudentRegistration.mirror_to_sis.

The gate only applies to registration sends (approved / approved_by_instructor),
calls Ethos.get_registration_eligibility with the section's reporting academic
period, and records a failed mirror (surfacing on the failed-mirror page) when
the SIS reports the student ineligible.
"""
import uuid
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models import CustomUser
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.course import Course, Cohort
from cis.models.term import Term, AcademicYear
from cis.services.tenant_services import get_tenant_service

try:
    from ethos.ethos.models import EthosLog
except ImportError:
    from ethos.models import EthosLog


PERIOD_ID = 'c0496632-88d2-4fac-95e6-d44234c99ed5'
ETHOS_PATH = 'ethos.ethos.library.ethos.Ethos'


class MirrorEligibilityGateTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        # mirror_to_sis(request=None) and the StudentRegistration post_save
        # signal both fall back to CustomUser.objects.get(username='cron').
        CustomUser.objects.create_user(
            username='cron', email='cron@example.com', password='x')

        # mirror_to_sis now gates on the configured sis_mirror_trigger statuses
        # (registration_status_email setting) rather than a hardcoded list.
        from cis.settings.registration_status_email import registration_status_email
        from cis.models.settings import Setting
        Setting.objects.update_or_create(
            key=registration_status_email.key,
            defaults={'value': {'sis_mirror_trigger': [
                'approved', 'registered', 'dropped',
                'withdrawn', 'approved_by_instructor',
            ]}})

        cohort = Cohort.objects.create(name='Astronomy', designator='A')
        course = Course.objects.create(
            catalog_number='001', title='Descriptive Astronomy',
            name='A 001', cohort=cohort)
        ay = AcademicYear.objects.create(name='2026-2027')
        term = Term.objects.create(label='Fall 2026', code='26FA', academic_year=ay)

        self.section = ClassSection.objects.create(
            course=course, term=term,
            class_number='A-001-3428', section_number='3428',
            external_sis_id=uuid.uuid4(),
            meta={'reportingAcademicPeriod': {'id': PERIOD_ID}},
        )

        student_user = CustomUser.objects.create_user(
            username='stu', email='stu@example.com', password='x',
            first_name='Avi', last_name='Codtest')
        self.student = Student.objects.create(user=student_user, sis_id=uuid.uuid4())

        self.reg = StudentRegistration.objects.create(
            student=self.student, class_section=self.section,
            status='approved', status_changed_on={},
        )

    def _make_ethos_log(self):
        # response body carries a valid UUID so _record_mirror_success can
        # assign it to the UUIDField StudentRegistration.sis_id.
        return EthosLog.objects.create(
            method='POST',
            url='https://integrate.elluciancloud.com/api/section-registrations',
            message_type='class_registered',
            request_body={}, response_status=200,
            response_body='{"id": "11111111-1111-1111-1111-111111111111"}',
        )

    @patch(ETHOS_PATH)
    def test_ineligible_registration_is_blocked_and_marked_failed(self, MockEthos):
        client = MockEthos.return_value
        client.get_registration_eligibility.return_value = {
            'eligibility_status': 'ineligible',
            'alternate_pin': 'notRequired',
            'start_on': '2026-04-21', 'end_on': '2026-12-04',
            'ineligibility_reasons': ['You must be a student for the term.'],
        }

        ran, summary = get_tenant_service('registration').mirror_to_sis(self.reg)

        client.get_registration_eligibility.assert_called_once_with(
            str(self.student.sis_id), PERIOD_ID)
        client.mirror_registration.assert_not_called()

        self.reg.refresh_from_db()
        self.assertEqual(self.reg.last_mirror_status, 'failed')
        self.assertIn('You must be a student for the term.', self.reg.last_mirror_error)
        self.assertIsNotNone(self.reg.last_mirror_at)
        # The failed-mirror page filters exactly on last_mirror_status='failed'.
        self.assertTrue(
            StudentRegistration.objects.filter(
                last_mirror_status='failed', id=self.reg.id).exists())

    @patch(ETHOS_PATH)
    def test_ineligible_with_no_reasons_uses_fallback_message(self, MockEthos):
        client = MockEthos.return_value
        client.get_registration_eligibility.return_value = {
            'eligibility_status': 'ineligible',
            'alternate_pin': 'notRequired',
            'start_on': '2026-04-21', 'end_on': '2026-12-04',
            'ineligibility_reasons': [],
        }

        get_tenant_service('registration').mirror_to_sis(self.reg)

        client.mirror_registration.assert_not_called()
        self.reg.refresh_from_db()
        self.assertEqual(self.reg.last_mirror_status, 'failed')
        self.assertEqual(self.reg.last_mirror_error, 'Student not eligible to register')

    @patch(ETHOS_PATH)
    def test_eligible_registration_proceeds_to_mirror(self, MockEthos):
        client = MockEthos.return_value
        client.get_registration_eligibility.return_value = {
            'eligibility_status': 'eligible', 'alternate_pin': 'notRequired',
            'start_on': '2026-04-21', 'end_on': '2026-12-04',
            'ineligibility_reasons': [],
        }
        client.mirror_registration.return_value = (True, self._make_ethos_log())

        get_tenant_service('registration').mirror_to_sis(self.reg)

        client.get_registration_eligibility.assert_called_once_with(
            str(self.student.sis_id), PERIOD_ID)
        client.mirror_registration.assert_called_once()
        self.reg.refresh_from_db()
        self.assertEqual(self.reg.last_mirror_status, 'success')

    @patch(ETHOS_PATH)
    def test_missing_reporting_period_proceeds_without_eligibility_check(self, MockEthos):
        client = MockEthos.return_value
        client.mirror_registration.return_value = (True, self._make_ethos_log())
        self.section.meta = {}  # no reportingAcademicPeriod
        self.section.save()

        get_tenant_service('registration').mirror_to_sis(self.reg)

        client.get_registration_eligibility.assert_not_called()
        client.mirror_registration.assert_called_once()

    @patch(ETHOS_PATH)
    def test_drop_status_is_not_gated(self, MockEthos):
        client = MockEthos.return_value
        client.mirror_registration.return_value = (True, self._make_ethos_log())
        self.reg.status = 'dropped'
        self.reg.save()

        get_tenant_service('registration').mirror_to_sis(self.reg)

        client.get_registration_eligibility.assert_not_called()
        client.mirror_registration.assert_called_once()
