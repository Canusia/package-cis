from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.teacher import Teacher


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class TeacherTabDispatchTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.user = CustomUser.objects.create_superuser(
            username='teachertabtest', email='teachertabtest@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)

        # Teacher requires a CustomUser via OneToOneField; all other fields are
        # optional (blank/null allowed) so a minimal fixture is just user + status.
        teacher_user = CustomUser.objects.create_user(
            username='teacher1', email='teacher1@example.com', password='x')
        self.teacher = Teacher.objects.create(
            user=teacher_user,
            status='active',
        )

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def test_unknown_tab_returns_404(self):
        resp = self.client.get(reverse('cis:instructor_tab', args=[self.teacher.id, 'nope']))
        self.assertEqual(resp.status_code, 404)

    def test_lazy_tabs_render(self):
        for slug in ['sections', 'visits', 'drop_wd', 'courses', 'notes']:
            resp = self.client.get(reverse('cis:instructor_tab', args=[self.teacher.id, slug]))
            self.assertEqual(resp.status_code, 200, slug)
        c = self.client.get(reverse('cis:instructor_tab', args=[self.teacher.id, 'courses']))
        self.assertIn('tbl_teacher_course_certificates', c.content.decode())
        n = self.client.get(reverse('cis:instructor_tab', args=[self.teacher.id, 'notes']))
        self.assertIn('tbl_teacher_notes', n.content.decode())

    def test_eager_tabs_render(self):
        for slug, needle in [('highschools', 'dataTable'),
                             ('ed_background', 'csrfmiddlewaretoken'),
                             ('files', 'name="action" value="upload_file"'),
                             ('migrate', 'csrfmiddlewaretoken')]:
            resp = self.client.get(reverse('cis:instructor_tab', args=[self.teacher.id, slug]))
            self.assertEqual(resp.status_code, 200, slug)
            self.assertIn(needle, resp.content.decode(), slug)

    def test_detail_page_renders_tabs_loop(self):
        resp = self.client.get(reverse('cis:instructor', args=[self.teacher.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for slug in ['highschools', 'courses', 'sections', 'ed_background',
                     'files', 'visits', 'notes', 'drop_wd', 'migrate']:
            self.assertIn('href="#%s"' % slug, body)
        self.assertNotIn('href="#course_schedule"', body)
        self.assertNotIn('href="#events"', body)
        self.assertIn('id="courses" data-tab-url=', body)
        self.assertIn('tab_loader.js', body)
