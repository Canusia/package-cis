"""Forced password change on the CE dashboard (package-cis#55).

`cisForceSetPasswordForm.save()` calls `set_password()`, which rotates the
session auth hash; without `update_session_auth_hash()` the next click lands on
the login page. The form also must not be `frm_ajax`: ActionRegistry hijacks
those and expects a JSON envelope, so the save succeeded but the page threw.
"""
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.views.password_management import cisForceSetPasswordForm

NEW_PASSWORD = 'Tr1cky-Horse-Battery-42'


class ForceSetPasswordDashboardTests(TestCase):
    def setUp(self):
        self._saved_receivers = list(user_logged_in.receivers)
        user_logged_in.receivers = []
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.user = CustomUser.objects.create_superuser(
            username='forcepw', email='forcepw@example.com', password='Old-Passw0rd-xyz')
        self.user.require_password_reset = True
        self.user.save()
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)
        self.url = reverse('cis:dashboard')

    def tearDown(self):
        user_logged_in.receivers = self._saved_receivers

    def _change_password(self):
        return self.client.post(self.url, {
            'action': 'force_set_password',
            'new_password1': NEW_PASSWORD,
            'new_password2': NEW_PASSWORD,
        })

    def test_saving_keeps_the_user_logged_in(self):
        resp = self._change_password()
        self.assertRedirects(resp, self.url, fetch_redirect_response=False)

        # the next request must still be authenticated, not bounced to login
        follow = self.client.get(self.url)
        self.assertEqual(follow.status_code, 200)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertFalse(self.user.require_password_reset)

    def test_saving_confirms_with_a_popup(self):
        resp = self._change_password()
        page = self.client.get(resp['Location']).content.decode()
        self.assertIn('Password Updated', page)

    def test_modal_renders_once(self):
        page = self.client.get(self.url).content.decode()
        self.assertEqual(page.count('id="passwordChangeModal"'), 1)

    def test_form_is_a_plain_post_not_frm_ajax(self):
        for kwargs in ({}, {'use_ajax': True}, {'use_ajax': False}):
            form = cisForceSetPasswordForm(self.user, **kwargs)
            self.assertNotIn('frm_ajax', form.helper.form_class or '', kwargs)
