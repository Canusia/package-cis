from django.test import TestCase

from cis.forms.teacher import TeacherCourseForm


class TeacherCourseFormFieldsTest(TestCase):
    def test_form_declares_renewal_date_fields(self):
        # Field declarations are class-level; no DB needed to assert presence.
        self.assertIn('expires_on', TeacherCourseForm.base_fields)
        self.assertIn('renewal_required_by', TeacherCourseForm.base_fields)
        self.assertIn('last_renewed_on', TeacherCourseForm.base_fields)

    def test_renewal_date_fields_are_optional(self):
        self.assertFalse(TeacherCourseForm.base_fields['expires_on'].required)
        self.assertFalse(TeacherCourseForm.base_fields['renewal_required_by'].required)
        self.assertFalse(TeacherCourseForm.base_fields['last_renewed_on'].required)
