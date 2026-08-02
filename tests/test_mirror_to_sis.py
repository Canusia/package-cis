"""Tests for mirror_to_sis bookkeeping (EthosLog helpers + field wiring).

Full integration coverage of mirror_to_sis is exercised via the Task 6
manual smoke test (it seeds a failed row through the ORM and confirms
the failed-mirror page renders it). These unit tests cover the helpers
new code paths depend on.
"""

import uuid
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import TestCase

try:
    from ethos.ethos.models import EthosLog
except ImportError:
    from ethos.models import EthosLog

from cis.models import CustomUser
from cis.models.section import StudentRegistration, ClassSection
from cis.models.student import Student
from cis.models.course import Course, Cohort
from cis.models.term import Term, AcademicYear
from cis.services.tenant_services import get_tenant_service

ETHOS_PATH = 'ethos.ethos.library.ethos.Ethos'


class EthosLogHelperTests(TestCase):

    def _log(self, **overrides):
        kw = dict(
            method='POST',
            url='https://integrate.elluciancloud.com/api/section-registrations',
            message_type='class_registered',
            request_body={},
            response_status=200,
            response_body='{}',
        )
        kw.update(overrides)
        return EthosLog.objects.create(**kw)

    def test_response_json_parses_valid_body(self):
        log = self._log(response_body='{"id": "abc", "n": 1}')
        self.assertEqual(log.response_json, {'id': 'abc', 'n': 1})

    def test_response_json_returns_empty_on_invalid(self):
        log = self._log(response_body='not json')
        self.assertEqual(log.response_json, {})

    def test_response_json_returns_empty_on_blank(self):
        log = self._log(response_body='')
        self.assertEqual(log.response_json, {})

    def test_error_message_blank_on_success(self):
        log = self._log(response_status=200, response_body='{"id":"x"}')
        self.assertEqual(log.error_message, '')

    def test_error_message_extracts_errors_array(self):
        log = self._log(
            response_status=400,
            response_body='{"errors":[{"message":"bad student"}]}',
        )
        self.assertEqual(log.error_message, 'bad student')

    def test_error_message_extracts_top_level_message(self):
        log = self._log(
            response_status=500,
            response_body='{"message":"server exploded"}',
        )
        self.assertEqual(log.error_message, 'server exploded')

    def test_error_message_falls_back_to_truncated_body(self):
        log = self._log(response_status=500, response_body='oops' * 200)
        msg = log.error_message
        self.assertEqual(len(msg), 500)
        self.assertTrue(msg.startswith('oops'))


class StudentRegistrationFieldsTests(TestCase):
    """Confirms the new fields exist on the model with expected types."""

    def test_mirror_status_choices(self):
        choices = dict(StudentRegistration._meta.get_field('last_mirror_status').choices)
        self.assertIn('success', choices)
        self.assertIn('failed', choices)
        self.assertIn('skipped', choices)

    def test_mirror_logs_target_is_ethos_ethoslog(self):
        f = StudentRegistration._meta.get_field('mirror_logs')
        self.assertEqual(f.related_model, EthosLog)

    def test_last_mirror_at_indexed(self):
        f = StudentRegistration._meta.get_field('last_mirror_at')
        self.assertTrue(f.db_index)


class MirrorableStatusesTests(TestCase):
    """mirror_to_sis gates on the configured sis_mirror_trigger, not a hardcoded list."""

    def _set_trigger(self, statuses):
        from cis.settings.registration_status_email import registration_status_email
        from cis.models.settings import Setting
        Setting.objects.update_or_create(
            key=registration_status_email.key,
            defaults={'value': {'sis_mirror_trigger': statuses}})

    def test_reads_configured_sis_mirror_trigger(self):
        from myce_tenant_configs.services import registration as reg_service
        self._set_trigger(['registered', 'dropped'])
        self.assertEqual(reg_service.mirrorable_statuses(), ['registered', 'dropped'])

    def test_empty_when_unconfigured(self):
        from myce_tenant_configs.services import registration as reg_service
        from cis.settings.registration_status_email import registration_status_email
        from cis.models.settings import Setting
        Setting.objects.filter(key=registration_status_email.key).delete()
        self.assertEqual(reg_service.mirrorable_statuses(), [])


class MirrorStatusSyncTests(TestCase):
    """On a successful mirror, registration.status is set to the SIS-confirmed
    sectionRegistrationStatusReason, and the just-mirrored row is not re-queued
    by the post_save sis_mirror_trigger signal."""

    def setUp(self):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.create_user(
            username='cron', email='cron@example.com', password='x')

        from cis.settings.registration_status_email import registration_status_email
        from cis.models.settings import Setting
        Setting.objects.update_or_create(
            key=registration_status_email.key,
            defaults={'value': {'sis_mirror_trigger': [
                'approved', 'registered', 'dropped', 'withdrawn',
            ]}})

        cohort = Cohort.objects.create(name='Astronomy', designator='A')
        course = Course.objects.create(
            catalog_number='001', title='Descriptive Astronomy',
            name='A 001', cohort=cohort)
        ay = AcademicYear.objects.create(name='2026-2027')
        term = Term.objects.create(label='Fall 2026', code='26FA', academic_year=ay)

        # meta={} (no reportingAcademicPeriod) => eligibility gate is skipped.
        self.section = ClassSection.objects.create(
            course=course, term=term,
            class_number='A-001-3428', section_number='3428',
            external_sis_id=uuid.uuid4(), meta={},
        )

        student_user = CustomUser.objects.create_user(
            username='stu', email='stu@example.com', password='x',
            first_name='Avi', last_name='Codtest')
        self.student = Student.objects.create(user=student_user, sis_id=uuid.uuid4())

        self.reg = StudentRegistration.objects.create(
            student=self.student, class_section=self.section,
            status='approved', status_changed_on={},
        )

    def _success_log(self, body):
        return EthosLog.objects.create(
            method='POST',
            url='https://integrate.elluciancloud.com/api/section-registrations',
            message_type='class_registered',
            request_body={}, response_status=200, response_body=body,
        )

    @patch(ETHOS_PATH)
    def test_status_synced_to_section_registration_status_reason(self, MockEthos):
        client = MockEthos.return_value
        client.mirror_registration.return_value = (True, self._success_log(
            '{"id": "215359a9-6824-48cb-90a5-223020b51408",'
            ' "status": {"registrationStatus": "registered",'
            ' "sectionRegistrationStatusReason": "registered"}}'
        ))

        ran, summary = get_tenant_service('registration').mirror_to_sis(self.reg)

        self.assertTrue(ran)
        self.reg.refresh_from_db()
        self.assertEqual(self.reg.status, 'registered')
        self.assertEqual(self.reg.last_mirror_status, 'success')
        # The just-mirrored row must NOT be re-queued even though 'registered'
        # is a sis_mirror_trigger status (post_save would otherwise set it True).
        self.assertFalse(self.reg.needs_mirroring)

    @patch(ETHOS_PATH)
    def test_status_unchanged_when_response_has_no_reason(self, MockEthos):
        client = MockEthos.return_value
        client.mirror_registration.return_value = (True, self._success_log(
            '{"id": "215359a9-6824-48cb-90a5-223020b51408"}'
        ))

        get_tenant_service('registration').mirror_to_sis(self.reg)

        self.reg.refresh_from_db()
        self.assertEqual(self.reg.status, 'approved')   # untouched
        self.assertEqual(self.reg.last_mirror_status, 'success')
        self.assertFalse(self.reg.needs_mirroring)
