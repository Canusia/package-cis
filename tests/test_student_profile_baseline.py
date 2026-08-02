"""Frozen snapshot of the student-profile form surface, recorded before the
field declarations moved to myce_tenant_configs. Any drift here means the
relocation changed behavior, which it must not."""
from django.test import TestCase

# Recorded from the pre-relocation form on 2026-07-30.
BASE_FIELDS = ['first_name', 'preferred_name', 'last_name', 'middle_name', 'other_last_names_used', 'email', 'password', 'confirm_password', 'permanent_address_country', 'permanent_address', 'permanent_address2', 'city', 'county', 'state', 'zip_code', 'same_as_permanent', 'mailing_country', 'mailing_address', 'mailing_address2', 'mailing_city', 'mailing_county', 'mailing_state', 'mailing_zip_code', 'preferred_phone', 'home_phone', 'cell_phone', 'cell_phone_opt_in', 'legal_sex', 'gender', 'date_of_birth', 'country_of_birth', 'primary_citizenship', 'ssn', 'verify_student_ssn', 'hispanic', 'ethnicity', 'parent_guardian_type', 'parent_first_name', 'parent_last_name', 'parent_email', 'parent_phone', 'highschool', 'start_date', 'cte', 'graduation_date', 'new_highschool_name', 'new_highschool_counselor_name', 'new_highschool_counselor_email', 'current_grade_level', 'signature']
EDITABLE_FIELDS = ['permanent_address_country', 'permanent_address', 'permanent_address2', 'city', 'state', 'zip_code', 'mailing_country', 'mailing_address', 'mailing_address2', 'mailing_city', 'mailing_state', 'mailing_zip_code', 'same_as_permanent', 'preferred_phone', 'cell_phone', 'home_phone', 'cell_phone_opt_in', 'highschool', 'cte', 'parent_guardian_type', 'parent_first_name', 'parent_last_name', 'parent_email', 'parent_phone', 'parent2_email', 'parent2_phone', 'email', 'qualify_tuition_assistance', 'parent1_education_level', 'parent2_education_level', 'parent1_interest', 'parent2_interest', 'confirm_term', 'signature', 'sevis_id', 'graduation_date', 'gender_identity', 'gender_pronoun', 'ethnicity', 'hispanic', 'legal_sex', 'preferred_first_name']
CIS_EXTRA_FIELDS = ['psid', 'alt_username', 'secondary_email', 'id']


class StudentProfileBaselineTest(TestCase):

    def test_base_form_declares_the_same_fields_in_the_same_order(self):
        from cis.forms.student_profile import StudentProfileForm
        self.assertEqual(list(StudentProfileForm.base_fields), BASE_FIELDS)

    def test_editable_default_is_unchanged(self):
        from cis.forms.student_profile import tenant_editable_fields
        self.assertEqual(list(tenant_editable_fields()), EDITABLE_FIELDS)

    def test_ce_form_adds_exactly_the_admin_fields(self):
        from cis.forms.student_profile import StudentCISForm, StudentProfileForm
        extra = [n for n in StudentCISForm.base_fields
                 if n not in StudentProfileForm.base_fields]
        self.assertEqual(extra, CIS_EXTRA_FIELDS)

    def test_profile_fields_vocabulary_is_unchanged(self):
        from cis.settings.student_profile import (
            SIGNUP_MECHANIC_FIELDS, profile_fields)
        # Sorted, deliberately: the set must be identical, while the order
        # intentionally changed for start_date / graduation_date.
        self.assertEqual(
            sorted(profile_fields()),
            sorted(n for n in BASE_FIELDS if n not in SIGNUP_MECHANIC_FIELDS))
