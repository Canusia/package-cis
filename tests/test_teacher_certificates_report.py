import datetime

from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone

from cis.models.customuser import CustomUser
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate
from cis.models.highschool import HighSchool
from cis.models.course import Course, Cohort
from cis.reports.teacher_certificates import teacher_certificates


class TeacherCertificatesReportTest(TestCase):
    def setUp(self):
        # TeacherHighSchool.save() adds the 'instructor' group to the teacher's user.
        Group.objects.get_or_create(name='instructor')

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

    def _cert(self, days, course=None):
        return TeacherCourseCertificate.objects.create(
            teacher_highschool=self.ths, course=course or self.course,
            status='Teaching',
            expires_on=timezone.localdate() + datetime.timedelta(days=days))

    def _course2(self):
        return Course.objects.create(
            name='MATH& 141', title='Precalculus I',
            catalog_number='141', cohort=self.cohort, status='Active')

    def test_window_filters_certs(self):
        inside = self._cert(30)
        outside = self._cert(200, course=self._course2())
        qs = teacher_certificates().filtered_queryset(window_days=90)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(inside.id, ids)
        self.assertNotIn(outside.id, ids)

    def test_blank_window_returns_all(self):
        # window_days is optional; with no window, all certificates are returned.
        inside = self._cert(30)
        outside = self._cert(200, course=self._course2())
        ids = set(
            teacher_certificates().filtered_queryset().values_list('id', flat=True))
        self.assertIn(inside.id, ids)
        self.assertIn(outside.id, ids)

    def test_window_days_field_is_optional(self):
        self.assertFalse(teacher_certificates.base_fields['window_days'].required)
