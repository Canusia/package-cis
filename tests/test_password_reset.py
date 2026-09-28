"""#54: the Forgot Password form strips invisible characters and shows one error."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse

from cis.views.password_management import cisPasswordResetForm


class PasswordResetFormTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create(
            username='student1', email='student1@example.com')
        group, _ = Group.objects.get_or_create(name='student')
        group.user_set.add(self.user)

    def _form(self, email):
        return cisPasswordResetForm(None, {'email': email})

    def test_email_with_zero_width_space_finds_user(self):
        form = self._form('student1@example.com​')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['email'], 'student1@example.com')

    def test_email_with_invisible_chars_around_it_finds_user(self):
        form = self._form('﻿‌student1@example.com‍⁠')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['email'], 'student1@example.com')

    def test_invalid_email_does_not_add_lookup_error(self):
        form = self._form('student1@example,com')
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)
        self.assertEqual(form.non_field_errors(), [])


# DEBUG=True keeps the view's form free of the reCAPTCHA field.
@override_settings(DEBUG=True)
class ForgotPasswordViewTests(TestCase):

    def test_failed_request_shows_single_error(self):
        response = self.client.post(
            reverse('forgot_password'), {'email': 'nobody@example.com'})
        content = response.content.decode()
        self.assertIn('Failed while looking up email', content)
        self.assertNotIn('Unable to complete your request', content)
