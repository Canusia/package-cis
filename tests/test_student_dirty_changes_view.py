from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.signals import user_logged_in

from cis.models.customuser import CustomUser
from cis.models.student import Student
from django.contrib.auth.models import Group


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class StudentProfileChangesViewTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        Group.objects.get_or_create(name='student')
        Group.objects.get_or_create(name='ce')
        self.admin = CustomUser.objects.create_superuser(
            email='ce@x.com', password='pw', username='ce@x.com',
        )
        # Add admin to ce group in case @user_required check needs it
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.admin.groups.add(ce_group)
        self.client.force_login(self.admin)
        self.user = CustomUser.objects.create_user(
            email='stu@x.com', password='pw', username='stu@x.com',
            first_name='Old', last_name='Original',
        )
        self.student = Student.objects.create(user=self.user, application_status='draft')

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def test_view_returns_diff_since_profile_dirty_at(self):
        self.user.first_name = 'Old'; self.user.save()
        self.student.profile_dirty_at = timezone.now()
        self.student.save()
        self.user.first_name = 'New'; self.user.save()

        url = reverse('cis:student_profile_changes', args=[self.student.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('first_name', body)
        self.assertIn('New', body)

    def test_view_404s_for_unknown_student(self):
        import uuid
        url = reverse('cis:student_profile_changes', args=[uuid.uuid4()])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)


class StudentsIndexPageTabTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        Group.objects.get_or_create(name='student')
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.admin = CustomUser.objects.create_superuser(
            email='ce_idx@x.com', password='pw', username='ce_idx@x.com',
        )
        self.admin.groups.add(ce_group)
        self.client.force_login(self.admin)

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def test_ce_students_index_renders_dirty_tab(self):
        url = reverse('cis:students')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('href="#dirty"', body)
        self.assertIn('Profile Changes', body)
        self.assertIn('records_dirty', body)
