"""AccessRequestReviewForm and the public request form."""
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from cis.forms.highschool import AccessRequestReviewForm, HSAdminAccessRequestModelForm
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import HSAdministratorAccessRequest
from cis.services.access_request_review import MISSING_RESET_LINK


class ReviewFormTests(TestCase):
    def setUp(self):
        self.hs = HighSchool.objects.create(name='North High', code='NH')
        self.req = HSAdministratorAccessRequest.objects.create(
            name='Jane Doe', email='jane@example.com', phone='555',
            highschool=self.hs, role='Counselor')

    def data(self, **extra):
        data = {'name': 'Jane Doe', 'email': 'JANE@example.com', 'phone': '555',
                'highschool': str(self.hs.pk), 'role': 'Counselor', 'decide': '1'}
        data.update(extra)
        return data

    def form(self, **extra):
        return AccessRequestReviewForm(self.data(**extra), instance=self.req)

    def test_no_status_field(self):
        self.assertNotIn('status', AccessRequestReviewForm(instance=self.req).fields)

    def test_decision_required_when_deciding(self):
        form = self.form()
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['decision'], ['Choose Approve or Deny.'])

    def test_save_details_needs_no_decision_or_email(self):
        form = AccessRequestReviewForm(
            {**self.data(), 'save_details': '1', 'decide': ''}, instance=self.req)
        self.assertTrue(form.saving_details_only)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['email'], 'jane@example.com')

    def test_approve_requires_reset_link(self):
        form = self.form(decision='approve', email_subject='Hi', email_message='Hi {{name}}')
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['email_message'], [MISSING_RESET_LINK])

    def test_approve_valid(self):
        form = self.form(decision='approve', email_subject='Hi {{name}}',
                         email_message='Set it: {{ password_reset_link }}')
        self.assertTrue(form.is_valid(), form.errors)

    def test_deny_ignores_permissions_and_rejects_reset_link(self):
        form = self.form(decision='deny', email_subject='Sorry',
                         email_message='{{password_reset_link}}')
        self.assertFalse(form.is_valid())
        self.assertIn('only be used in an approval email', form.errors['email_message'][0])

        form = self.form(decision='deny', email_subject='Sorry', email_message='Sorry {{name}}')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['permissions'], [])
        self.assertIsNone(form.cleaned_data.get('scope'))

    def test_typo_blocks_with_suggestion(self):
        form = self.form(decision='deny', email_subject='Sorry {{nmae}}', email_message='x')
        self.assertFalse(form.is_valid())
        self.assertIn('Did you mean {{name}}?', form.errors['email_subject'][0])

    def test_empty_email_blocked(self):
        form = self.form(decision='deny', email_subject='', email_message='  ')
        self.assertFalse(form.is_valid())
        self.assertIn('email_subject', form.errors)
        self.assertIn('email_message', form.errors)

    def test_scope_must_belong_to_submitted_school(self):
        from cis.models.course import Campus
        other_hs = HighSchool.objects.create(name='South High', code='SH')
        campus = Campus.objects.create(name='Main', code='MAIN-1')
        form = self.form(decision='approve', highschool=str(other_hs.pk),
                         email_subject='Hi', email_message='{{password_reset_link}}',
                         scope=str(campus.pk))
        if 'scope' not in form.fields:
            self.skipTest('single-campus deployment: no scope field')
        self.assertFalse(form.is_valid())
        self.assertIn('scope', form.errors)


class PublicFormTests(TestCase):
    def test_public_form_fields_unchanged(self):
        request = RequestFactory().get('/highschool_admin/access_request')
        request.user = AnonymousUser()
        form = HSAdminAccessRequestModelForm(request=request)
        self.assertEqual(list(form.fields),
                         ['name', 'email', 'phone', 'highschool', 'role', 'captcha'])
