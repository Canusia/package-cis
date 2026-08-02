import datetime

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from cis.models.customuser import CustomUser
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate
from cis.models.highschool import HighSchool
from cis.models.course import Course, Cohort
from cis.models.settings import Setting
from cis.settings.teacher_certificate_renewal import teacher_certificate_renewal


class NotifyCertificateRenewalTest(TestCase):
    def setUp(self):
        # TeacherHighSchool.save() adds the 'instructor' group to the teacher's user.
        Group.objects.get_or_create(name='instructor')

        # 'cron' user is looked up by the command for note authorship.
        CustomUser.objects.create(username='cron', email='cron@example.com')

        self.user = CustomUser.objects.create(
            username='inst1', email='inst1@example.com',
            first_name='Pat', last_name='Lee')
        self.teacher = Teacher.objects.create(user=self.user, status='active')
        self.hs = HighSchool.objects.create(name='Test HS', status='Active')
        self.ths = TeacherHighSchool.objects.create(
            teacher=self.teacher, highschool=self.hs, status='In the Program')
        self.cohort = Cohort.objects.create(name='English', designator='ENGL')
        self.course = Course.objects.create(
            name='ENGL& 101', title='English Composition',
            catalog_number='101', cohort=self.cohort, status='Active')

        # Enable the setting (Debug avoids hitting real recipients).
        setting = Setting(key=teacher_certificate_renewal.key)
        setting.value = {
            'is_active': 'Debug',
            'window_days': '90',
            'frequency': '7',
            'email_subject': 'Renew your credential',
            'email_message': 'Hi {{teacher_first_name}}, {{course_name}} is due {{renewal_due_date}}.',
        }
        setting.save()

    def _cert(self, due_offset_days):
        return TeacherCourseCertificate.objects.create(
            teacher_highschool=self.ths,
            course=self.course,
            status='Teaching',
            expires_on=timezone.localdate() + datetime.timedelta(days=due_offset_days),
        )

    def test_stamps_cert_inside_window(self):
        cert = self._cert(30)
        call_command('notify_certificate_renewal')
        cert.refresh_from_db()
        self.assertEqual(cert.last_reminder_sent_on, timezone.localdate())

    def test_skips_cert_outside_window(self):
        cert = self._cert(200)
        call_command('notify_certificate_renewal')
        cert.refresh_from_db()
        self.assertIsNone(cert.last_reminder_sent_on)

    def test_skips_recently_reminded_cert(self):
        cert = self._cert(30)
        cert.last_reminder_sent_on = timezone.localdate() - datetime.timedelta(days=2)
        cert.save()
        call_command('notify_certificate_renewal')
        cert.refresh_from_db()
        # frequency=7, only 2 days passed -> unchanged
        self.assertEqual(
            cert.last_reminder_sent_on,
            timezone.localdate() - datetime.timedelta(days=2),
        )

    def test_uses_renewal_required_by_over_expires_on(self):
        # expires_on is far out, but renewal_required_by is inside the window:
        # the cert must still be selected (renewal_due_date precedence).
        cert = TeacherCourseCertificate.objects.create(
            teacher_highschool=self.ths,
            course=self.course,
            status='Teaching',
            expires_on=timezone.localdate() + datetime.timedelta(days=300),
            renewal_required_by=timezone.localdate() + datetime.timedelta(days=20),
        )
        call_command('notify_certificate_renewal')
        cert.refresh_from_db()
        self.assertEqual(cert.last_reminder_sent_on, timezone.localdate())
