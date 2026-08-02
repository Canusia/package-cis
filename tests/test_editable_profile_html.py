from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models.customuser import CustomUser
from cis.models.settings import Setting
from cis.models.student import Student
from cis.settings.student_profile import student_profile, DEFAULT_REVIEW_TEMPLATE


class EditableProfileAsHTMLTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})
        cls.user = CustomUser.objects.create(
            username='html_test',
            email='html_test@example.com',
            first_name='Jane',
            last_name='Doe',
            psid='-',
        )
        cls.student = Student.objects.create(user=cls.user, meta={})

    def test_renders_setting_template_with_student_context(self):
        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {
                'profile_review_template': '<p>{{ student.user.first_name }}</p>',
            }},
        )
        self.assertEqual(self.student.editable_profile_asHTML(), '<p>Jane</p>')

    def test_falls_back_to_default_template_when_setting_missing(self):
        Setting.objects.filter(key=student_profile.key).delete()
        html = self.student.editable_profile_asHTML()
        self.assertIn('FIRST NAME', html)
        self.assertIn('Jane', html)

    def test_falls_back_to_default_template_when_template_blank(self):
        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {'profile_review_template': ''}},
        )
        html = self.student.editable_profile_asHTML()
        self.assertIn('FIRST NAME', html)
        self.assertIn('Jane', html)
