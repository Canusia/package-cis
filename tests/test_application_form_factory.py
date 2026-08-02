from unittest.mock import patch
from django.contrib.auth.models import Group
from django.test import TestCase
from cis.forms.application_form import get_application_form
from cis.forms.student_profile import StudentProfileForm
from cis.forms.application_form import SpecDrivenApplicationForm
from cis.models import CustomUser
from cis.models.student import Student


class FactoryTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        u = CustomUser.objects.create_user(username='s', email='s@example.com', password='x')
        self.student = Student.objects.create(user=u)

    def test_no_spec_returns_legacy_form(self):
        with patch('cis.forms.application_form.get_application_fields', return_value=None):
            form = get_application_form(student=self.student, request=None)
        self.assertIsInstance(form, StudentProfileForm)   # ewu path unchanged

    def test_spec_returns_spec_driven_form(self):
        spec = [{'name': 'agree', 'type': 'agreement', 'label': 'I agree',
                 'required': True, 'target': 'meta'}]
        with patch('cis.forms.application_form.get_application_fields', return_value=spec):
            form = get_application_form(student=self.student, request=None)
        self.assertIsInstance(form, SpecDrivenApplicationForm)
