"""The access request review page end to end."""
from unittest import mock

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase, override_settings
from django.urls import reverse

from cis.models import CustomUser
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministratorAccessRequest, HSAdministratorPosition,
)
from cis.models.settings import Setting

SEND = 'cis.models.highschool_administrator.send_html_mail'


@override_settings(DEBUG=False)
@mock.patch.object(CustomUser, 'get_password_reset_link', return_value='https://reset/x')
class ReviewViewTests(TestCase):
    def setUp(self):
        self._receivers, user_logged_in.receivers = list(user_logged_in.receivers), []
        Group.objects.get_or_create(name='highschool_admin')
        ce, _ = Group.objects.get_or_create(name='ce')
        self.staff = CustomUser.objects.create_superuser(
            username='rv', email='rv@example.com', password='x')
        self.staff.groups.add(ce)
        self.client.force_login(self.staff)
        Setting.objects.create(key='cis.settings.access_request', value={
            'approved_subject': 'Welcome {{name}}',
            'approved_email': 'Set it: {{password_reset_link}}',
            'denied_subject': 'About your request', 'denied_email': 'Sorry {{name}}',
        })
        self.hs = HighSchool.objects.create(name='North High', code='NH')
        self.req = HSAdministratorAccessRequest.objects.create(
            name='Jane Doe', email='jane@example.com', phone='555',
            highschool=self.hs, role='Counselor')
        self.url = reverse('cis:hs_admin_access_request', args=[self.req.pk])

    def tearDown(self):
        user_logged_in.receivers = self._receivers

    def post(self, **extra):
        data = {'name': 'Jane Doe', 'email': 'jane@example.com', 'phone': '555',
                'highschool': str(self.hs.pk), 'role': 'Counselor'}
        data.update(extra)
        return self.client.post(self.url, data)

    def test_get_renders_three_steps_and_templates(self, _link):
        body = self.client.get(self.url).content.decode()
        self.assertNotIn('name="status"', body)
        self.assertIn('Do you approve or deny this request?', body)
        self.assertIn('id="ar-email-templates"', body)
        self.assertIn('Set it: {{password_reset_link}}', body)
        self.assertIn('access_request_review.js', body)
        self.assertIn('name="save_details"', body)

    def test_save_details_sends_nothing(self, _link):
        with mock.patch(SEND) as send:
            self.post(name='Janet Doe', save_details='1')
        self.req.refresh_from_db()
        self.assertEqual((self.req.name, self.req.status), ('Janet Doe', 'Submitted'))
        send.assert_not_called()

    def test_approve_flow(self, _link):
        with mock.patch(SEND) as send:
            response = self.post(decide='1', decision='approve',
                                 email_subject='Hi {{name}}',
                                 email_message='Edited {{password_reset_link}}')
        self.assertRedirects(response, self.url)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'Approved')
        self.assertEqual(send.call_args.args[1], 'Edited https://reset/x')
        self.assertTrue(HSAdministratorPosition.objects.filter(highschool=self.hs).exists())

    def test_invalid_email_rerenders_with_errors_and_does_nothing(self, _link):
        with mock.patch(SEND) as send:
            response = self.post(decide='1', decision='approve',
                                 email_subject='Hi', email_message='Hi {{nmae}}')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Did you mean {{name}}?')
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'Submitted')
        send.assert_not_called()

    def test_broken_settings_template_blocks_send_with_message(self, _link):
        Setting.objects.filter(key='cis.settings.access_request').update(value={
            'approved_subject': 'Welcome {name}', 'approved_email': 'Hi {{nmae}}',
            'denied_subject': 'x', 'denied_email': 'y'})
        self.assertEqual(self.client.get(self.url).status_code, 200)
        with mock.patch(SEND) as send:
            response = self.post(decide='1', decision='approve',
                                 email_subject='Welcome {name}', email_message='Hi {{nmae}}')
        self.assertContains(response, 'Use double braces')
        send.assert_not_called()

    def test_decided_request_shows_summary_not_form(self, _link):
        with mock.patch(SEND):
            self.post(decide='1', decision='deny', email_subject='x', email_message='Sorry')
        body = self.client.get(self.url).content.decode()
        self.assertNotIn('id="ar-review-form"', body)
        self.assertIn('Denied', body)
        self.assertIn(f'/ce/highschool/{self.hs.pk}', body)   # where the note lives

    def test_post_to_decided_request_does_nothing(self, _link):
        with mock.patch(SEND):
            self.post(decide='1', decision='deny', email_subject='x', email_message='Sorry')
        with mock.patch(SEND) as send:
            self.post(decide='1', decision='approve', email_subject='x',
                      email_message='{{password_reset_link}}')
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'Denied')
        send.assert_not_called()

    def test_complete_review_failure_is_reported_not_a_500(self, _link):
        with mock.patch(SEND) as send, mock.patch(
                'cis.services.access_request_review.complete_review',
                side_effect=RuntimeError('boom')):
            response = self.post(decide='1', decision='approve',
                                 email_subject='Hi', email_message='{{password_reset_link}}')
        self.assertLess(response.status_code, 500)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'Submitted')
        send.assert_not_called()
