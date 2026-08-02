from django.contrib.auth.models import Group
from django.test import TestCase

from cis.forms.application_form import SpecDrivenApplicationForm
from cis.models import CustomUser
from cis.models.student import Student

SPEC = [
    {'name': 'race', 'type': 'multichoice', 'label': 'Race', 'required': False,
     'target': 'meta', 'choices': ['Asian', 'White']},
    {'name': 'agree', 'type': 'agreement', 'label': 'I agree', 'required': True,
     'target': 'meta'},
]


class SpecDrivenFormTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        u = CustomUser.objects.create_user(username='s', email='s@example.com', password='x')
        self.student = Student.objects.create(user=u)

    def test_fields_built_from_spec_in_order(self):
        form = SpecDrivenApplicationForm(spec=SPEC, student=self.student)
        self.assertEqual(list(form.fields.keys()), ['race', 'agree'])

    def test_save_routes_meta_values_into_student_meta(self):
        form = SpecDrivenApplicationForm(
            spec=SPEC, student=self.student,
            data={'race': ['Asian'], 'agree': 'on'})
        self.assertTrue(form.is_valid(), form.errors)
        form.save(student=self.student)
        self.student.refresh_from_db()
        self.assertEqual(self.student.meta.get('race'), ['Asian'])
        self.assertTrue(self.student.meta.get('agree'))

    def test_save_returns_student_instance(self):
        """save() must match the StudentProfileForm.save() contract of
        returning the student (not a tuple), since complete_signup() in
        student/views/onboarding.py calls record.account_verified_on = ...
        and record.add_note(...) on the return value."""
        form = SpecDrivenApplicationForm(
            spec=SPEC, student=self.student,
            data={'race': ['Asian'], 'agree': 'on'})
        self.assertTrue(form.is_valid(), form.errors)
        returned = form.save(student=self.student)
        self.assertIs(returned, self.student)
