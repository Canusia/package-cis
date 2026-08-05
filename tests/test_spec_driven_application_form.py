from django.contrib.auth.models import Group
from django.test import TestCase

from cis.forms.application_form import SpecDrivenApplicationForm
from cis.models import CustomUser
from cis.models.settings import Setting
from cis.models.student import Student
from cis.settings.student_profile import student_profile

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


class FieldMessagesTests(TestCase):
    """The per-field label/help-text config reaches the application form, not
    just the profile form.

    `_load_field_labels_from_db` lives on MetaFormMixin and is covered there in
    isolation (test_meta_form_mixin_ordering); what was never asserted is that
    SpecDrivenApplicationForm actually calls it, so a refactor could drop the
    call and only the profile path would notice. ewu#35 was filed believing
    this behaviour was missing here — it is not, and this test is what makes
    that checkable instead of re-derivable by reading __init__.
    """

    def setUp(self):
        Group.objects.get_or_create(name='student')
        u = CustomUser.objects.create_user(
            username='fm', email='fm@example.com', password='x')
        self.student = Student.objects.create(user=u)

    def _write_messages(self, messages):
        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {'field_messages': messages}})

    def test_configured_label_and_help_text_override_the_spec_wording(self):
        self._write_messages({
            'race': {'label': 'Race / Ethnicity',
                     'help_text': 'Select <b>all</b> that apply.'}})
        form = SpecDrivenApplicationForm(spec=SPEC, student=self.student)
        self.assertEqual(str(form.fields['race'].label), 'Race / Ethnicity')
        self.assertEqual(str(form.fields['race'].help_text),
                         'Select <b>all</b> that apply.')
        # HTML in help text is deliberate and must survive rendering unescaped
        # (the profile path behaves the same way).
        self.assertIn('<b>all</b>', form['race'].as_widget() + str(
            form.fields['race'].help_text))

    def test_unconfigured_fields_keep_the_spec_wording(self):
        self._write_messages({'race': {'label': 'Race / Ethnicity'}})
        form = SpecDrivenApplicationForm(spec=SPEC, student=self.student)
        self.assertEqual(str(form.fields['agree'].label), 'I agree')

    def test_no_config_at_all_is_a_no_op(self):
        Setting.objects.filter(key=student_profile.key).delete()
        form = SpecDrivenApplicationForm(spec=SPEC, student=self.student)
        self.assertEqual(str(form.fields['race'].label), 'Race')
        self.assertEqual(str(form.fields['agree'].label), 'I agree')
