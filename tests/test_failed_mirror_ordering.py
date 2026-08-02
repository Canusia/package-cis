"""Regression tests for DataTables ordering on the Failed SIS Mirror tab.

The failed-mirror serializer exposes flat SerializerMethodFields
(student_name, class_section_str, ...). rest_framework_datatables maps the
DataTables `columns[i][name]` straight to an ORM path for order_by()/search,
so the inline template JS must send a real model field path (via each column's
`name:`), not the SerializerMethodField name, or ordering those columns raises
FieldError.
"""
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.course import Course, Cohort
from cis.models.term import Term, AcademicYear


def _disconnect_login_signal():
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class FailedMirrorOrderingTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()

        Group.objects.get_or_create(name='student')
        ce_group, _ = Group.objects.get_or_create(name='ce')

        if not CustomUser.objects.filter(username='cron').exists():
            CustomUser.objects.create_user(
                username='cron', email='cron@example.com', password='x')

        ay = AcademicYear.objects.create(name='2025-2026-FM')
        term = Term.objects.create(
            label='Fall 2025 FM', code='F25FM', academic_year=ay)
        cohort = Cohort.objects.create(name='FM Cohort', designator='FMC')
        course = Course.objects.create(
            catalog_number='201', title='FM Test', name='FM201', cohort=cohort)
        section = ClassSection.objects.create(
            course=course, term=term, class_number=88801, section_number='001')

        student_user = CustomUser.objects.create_user(
            username='fmstudent', email='fmstudent@example.com', password='x',
            first_name='Fm', last_name='Student')
        student = Student.objects.create(user=student_user)
        StudentRegistration.objects.create(
            student=student, class_section=section,
            status='approved', status_changed_on={},
            last_mirror_status='failed',
        )

        self.user = CustomUser.objects.create_superuser(
            username='fmtest', email='fmtest@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def test_page_js_uses_real_orm_paths_for_orderable_columns(self):
        resp = self.client.get(reverse('cis:registrations_failed_mirror'))
        self.assertEqual(resp.status_code, 200)
        c = resp.content
        self.assertIn(b'student.user.last_name', c)
        self.assertIn(b'student.user.psid', c)
        self.assertIn(b'class_section.course.name', c)
        self.assertIn(b'class_section.term.code', c)

    def _order_params(self, col_index, name):
        return {
            'format': 'datatables', 'draw': '1', 'start': '0', 'length': '30',
            'search[value]': '', 'search[regex]': 'false',
            'order[0][column]': str(col_index), 'order[0][dir]': 'asc',
            'columns[0][data]': '0',
            'columns[0][name]': '',
            'columns[0][orderable]': 'false',
            'columns[0][searchable]': 'false',
            f'columns[{col_index}][data]': 'x',
            f'columns[{col_index}][name]': name,
            f'columns[{col_index}][orderable]': 'true',
            f'columns[{col_index}][searchable]': 'true',
            f'columns[{col_index}][search][value]': '',
            f'columns[{col_index}][search][regex]': 'false',
        }

    def test_api_order_by_student_column_200(self):
        url = reverse('cis:failed_mirror_registrations-list')
        resp = self.client.get(
            url, self._order_params(1, 'student.user.last_name,student.user.first_name'))
        self.assertEqual(resp.status_code, 200, resp.content[:400])

    def test_api_order_by_section_and_term_200(self):
        url = reverse('cis:failed_mirror_registrations-list')
        for col, name in ((3, 'class_section.course.name'), (4, 'class_section.term.code')):
            resp = self.client.get(url, self._order_params(col, name))
            self.assertEqual(resp.status_code, 200, resp.content[:400])
