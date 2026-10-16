"""package-cis#74: "Apply for selected" on the student Course Requests tab must
reload the registrations table by its own id, not through window.refreshTable.

window.refreshTable is last-writer-wins: the Supporting Documents table on the
same page (and Notes, once opened) overwrite it, so the global reloaded the
wrong table and the new course request did not appear until a full reload.
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models.student import Student
from cis.services.table_configs import get_table_config

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class StudentClassesTabReloadTests(TestCase):
    def setUp(self):
        self._saved_receivers = list(user_logged_in.receivers)
        user_logged_in.receivers = []

        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@x.com'})
        stu_user = User.objects.create_user(
            username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        # Unverified students are visible to every CE user, so no campus setup.
        self.student = Student.objects.create(user=stu_user, account_verified=False)

        self.user = User.objects.create_superuser(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.client.force_login(self.user)

        self.table_id = get_table_config('registrations_table').build_config(
            variant='student_detail', api_url='/x?format=datatables',
        )['table_id']

    def tearDown(self):
        user_logged_in.receivers = self._saved_receivers

    def _classes_tab_body(self):
        resp = self.client.get(
            reverse('cis:student_tab', args=[self.student.id, 'classes']))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_apply_for_selected_reloads_registrations_table_by_id(self):
        body = self._classes_tab_body()
        self.assertTrue(self.table_id)
        self.assertIn(f"$('#{self.table_id}')", body)
        self.assertIn('$.fn.dataTable.isDataTable(', body)
        self.assertIn('.DataTable().ajax.reload(null, false)', body)

    def test_global_refresh_is_only_a_fallback(self):
        body = self._classes_tab_body()
        self.assertIn('.DataTable().ajax.reload(null, false)', body)
        by_id = body.index('.DataTable().ajax.reload(null, false)')
        fallback = body.index('window.refreshTable()')
        self.assertLess(by_id, fallback)
