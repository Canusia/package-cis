"""Regression: send_registrations_to_sis cron summary must be a clean string.

The per-record mirror_to_sis return (a list) was being assigned to the same
`summary` variable used as the string accumulator, so the trailing
`summary += "...string..."` extended the list character-by-character and the
cronlog rendered ['msg', '\\r', '\\n', 'S', 'u', ...].
"""
import uuid
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from cis.models import CustomUser
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.course import Course, Cohort
from cis.models.term import Term, AcademicYear
from cis.signals.crontab import cron_task_done

MODPATH = 'cis.management.commands.send_registrations_to_sis'


class SendRegistrationsToSisSummaryTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.create_user(
            username='cron', email='cron@example.com', password='x')
        cohort = Cohort.objects.create(name='Astronomy', designator='A')
        course = Course.objects.create(
            catalog_number='001', title='Descriptive Astronomy',
            name='A 001', cohort=cohort)
        ay = AcademicYear.objects.create(name='2026-2027')
        term = Term.objects.create(label='Fall 2026', code='26FA', academic_year=ay)
        self.section = ClassSection.objects.create(
            course=course, term=term,
            class_number='A-001-3428', section_number='3428',
            external_sis_id=uuid.uuid4())
        user = CustomUser.objects.create_user(
            username='stu', email='stu@example.com', password='x',
            first_name='Avi', last_name='Test')
        student = Student.objects.create(user=user, sis_id=uuid.uuid4())
        reg = StudentRegistration.objects.create(
            student=student, class_section=self.section,
            status='applied', status_changed_on={})
        # update() (not save()) so no mirror post_save fires during setup
        StudentRegistration.objects.filter(id=reg.id).update(
            status='approved', needs_mirroring=True)

    def test_summary_is_a_clean_string(self):
        captured = {}

        def _receiver(sender, **kwargs):
            captured['summary'] = kwargs.get('summary')
        cron_task_done.connect(_receiver)
        self.addCleanup(cron_task_done.disconnect, _receiver)

        svc = MagicMock()
        # mirror_to_sis returns (ran: bool, messages: list[str])
        svc.mirror_to_sis.return_value = (True, ['Testcaleb / Withdrawn - success'])

        with patch(f'{MODPATH}.get_tenant_service', return_value=svc), \
             patch(f'{MODPATH}.registration_status_email') as cfg:
            cfg.from_db.return_value = {'sis_mirror_trigger': ['approved']}
            call_command('send_registrations_to_sis', '--time', '2026-07-23 12:00:00')

        summary = captured['summary']
        self.assertIsInstance(summary, str)          # not a list of chars
        self.assertIn('Successfully sent - ', summary)
        self.assertIn('Held for parent consent - ', summary)
