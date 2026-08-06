import datetime
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from cis.forms.student_profile import (
    StudentCISForm,
    StudentEditableForm,
    StudentProfileForm,
    tenant_editable_fields,
)
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.note import StudentNote
from cis.models.student import Student
from cis.models.term import AcademicYear, Term
from cis.models.settings import Setting


class StudentProfileFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Student.save() expects a Group named "student".
        Group.objects.get_or_create(name="student")

        # Student.add_note() expects a CustomUser with username "cron".
        cls.cron_user = CustomUser.objects.create(
            username="cron",
            email="cron@example.com",
            first_name="Cron",
            last_name="Job",
        )

        cls.user = CustomUser.objects.create(
            username="student_user",
            email="student@example.com",
            first_name="Avi",
            last_name="Kadaji",
            primary_phone="+15095551234",
            secondary_phone="+15095559876",
            address1="123 Permanent St",
            city="Yakima",
            state="WA",
            postal_code="98901",
            country="US",
            date_of_birth=datetime.date(2015, 1, 15),
        )
        cls.student = Student.objects.create(
            user=cls.user,
            gender="m",
            notifications={"cell_phone_opt_in": "True"},
            meta={
                "preferred_name": "Avi",
                "mailing_address": "456 Mailing Ave",
            },
        )

        # Queryset configuration (Active, exclude name containing "career" for highschool;
        # include name containing "career" for CTE).
        cls.hs_regular = HighSchool.objects.create(
            name="Regular High School",
            code="RHS",
            status="Active",
        )
        cls.hs_career = HighSchool.objects.create(
            name="Career Academy High School",
            code="CAHS",
            status="Active",
        )

        # Term + Setting used by active_term() and DOB year widget configuration.
        cls.academic_year = AcademicYear.objects.create(name="2025-2026")
        cls.term = Term.objects.create(
            academic_year=cls.academic_year,
            code="2025A",
            label="Fall 2025",
            dates={},
        )

        prefix = cls._campus_prefix()
        cls.registrations_setting_key = f"{prefix}_cis_registrations"
        cls.student_profile_setting_key = f"{prefix}_student_profile"

        Setting.objects.create(
            key=cls.registrations_setting_key,
            value={
                "starting_birth_date": "01/01/2010",
                "ending_birth_date": "12/31/2012",
                "active_term": str(cls.term.id),
                "registration_terms": [],
            },
        )

        # Provide DB-driven field label/help_text used by _load_field_labels_from_db().
        # These live on the student_profile setting as a native dict; the legacy
        # signup.form_field_messages fallback is covered by
        # cis.tests.test_profile_field_messages.
        Setting.objects.create(
            key=cls.student_profile_setting_key,
            value={
                "field_messages": {
                    "first_name": {
                        "label": "New First Name",
                        "help_text": "New first name help.",
                    },
                }
            },
        )

    @staticmethod
    def _campus_prefix():
        # StudentProfileForm uses django settings' CAMPUS_CODE_PREFIX.
        from django.conf import settings

        return getattr(settings, "CAMPUS_CODE_PREFIX", "TEST")

    def test_init_configures_highschool_and_cte_querysets(self):
        form = StudentProfileForm(student=self.student)

        highschool_ids = list(form.fields["highschool"].queryset.values_list("id", flat=True))
        cte_ids = list(form.fields["cte"].queryset.values_list("id", flat=True))

        self.assertIn(self.hs_regular.id, highschool_ids)
        self.assertNotIn(self.hs_career.id, highschool_ids)

        self.assertIn(self.hs_career.id, cte_ids)
        self.assertNotIn(self.hs_regular.id, cte_ids)

    def test_init_sets_graduation_date_widget_bounds(self):
        form = StudentProfileForm(student=self.student)

        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)
        this_year = today.year
        if datetime.datetime.now().month >= 6:
            this_year += 1

        expected_min = tomorrow.isoformat()
        expected_max = f"{this_year + 4}-12-31"

        self.assertEqual(form.fields["graduation_date"].widget.attrs["min"], expected_min)
        self.assertEqual(form.fields["graduation_date"].widget.attrs["max"], expected_max)

    def test_init_sets_date_of_birth_widget_years_from_db(self):
        form = StudentProfileForm(student=self.student)
        widget = form.fields["date_of_birth"].widget

        self.assertTrue(hasattr(widget, "years"))
        self.assertTrue(set([2010, 2011, 2012]).issubset(set(widget.years)))
        # _populate_initial_from_instance() appends the user's DOB year if missing.
        self.assertIn(self.user.date_of_birth.year, widget.years)

    def test_loads_dynamic_labels_and_help_text_from_db(self):
        form = StudentProfileForm(student=self.student)

        self.assertEqual(form.fields["first_name"].label, "New First Name")
        # mark_safe returns SafeString; comparing via str() avoids SafeString vs str mismatch.
        self.assertEqual(str(form.fields["first_name"].help_text), "New first name help.")

    def test_populate_initial_normalizes_phone_and_sets_notifications_and_meta(self):
        form = StudentProfileForm(student=self.student)

        # phone normalization: +1 prefix stripped for primary/secondary phone.
        self.assertEqual(form.initial["cell_phone"], "5095551234")
        self.assertEqual(form.initial["home_phone"], "5095559876")

        # notification initial becomes boolean based on "True" string.
        self.assertEqual(form.initial["cell_phone_opt_in"], True)

        # meta fields pulled from student.meta
        self.assertEqual(form.initial["mailing_address"], "456 Mailing Ave")
        self.assertEqual(form.initial["permanent_address_country"], "US")

    def test_apply_declarative_copies_copies_mailing_address_when_same_as_permanent(self):
        form = StudentProfileForm(student=self.student)
        # MetaFormMixin.apply_declarative_copies() checks `name in self._errors`.
        # When the form hasn't been validated, Django can leave `_errors` as None.
        form._errors = {}

        cleaned = {
            "same_as_permanent": True,
            "permanent_address_country": "US",
            "permanent_address": "P Address",
            "city": "P City",
            "state": "WA",
            "zip_code": "98901",
            # Intentionally empty mailing fields to verify copy logic.
            "mailing_address": "",
            "mailing_city": "",
            "mailing_state": "",
            "mailing_zip_code": "",
        }

        form.apply_declarative_copies(cleaned)

        self.assertEqual(cleaned["mailing_address"], "P Address")
        self.assertEqual(cleaned["mailing_city"], "P City")
        self.assertEqual(cleaned["mailing_state"], "WA")
        self.assertEqual(cleaned["mailing_zip_code"], "98901")

    def test_clean_first_name_title_cases(self):
        form = StudentProfileForm(student=self.student)
        form.cleaned_data = {"first_name": "avi"}
        self.assertEqual(form.clean_first_name(), "Avi")

    def test_clean_last_name_title_cases(self):
        form = StudentProfileForm(student=self.student)
        form.cleaned_data = {"last_name": "kadaji"}
        self.assertEqual(form.clean_last_name(), "Kadaji")

    def test_clean_email_rejects_duplicates(self):
        CustomUser.objects.create(
            username="dup_user",
            email="dup@example.com",
            first_name="Dup",
            last_name="User",
        )

        form = StudentProfileForm(student=None)
        form.cleaned_data = {"email": "DUP@EXAMPLE.COM"}
        with self.assertRaises(ValidationError):
            form.clean_email()

    def test_clean_email_allows_non_duplicates(self):
        form = StudentProfileForm(student=self.student)
        form.cleaned_data = {"email": "unique@example.com"}
        self.assertEqual(form.clean_email(), "unique@example.com")

    def test_clean_date_of_birth_rejects_out_of_range(self):
        form = StudentProfileForm(student=self.student)
        form.cleaned_data = {"date_of_birth": datetime.date(2000, 1, 1)}
        with self.assertRaises(ValidationError):
            form.clean_date_of_birth()

    def test_clean_confirm_password_mismatch_raises(self):
        form = StudentProfileForm(student=self.student)
        form.cleaned_data = {"password": "Aa1!SecurePassword", "confirm_password": "different"}
        with self.assertRaises(ValidationError):
            form.clean_confirm_password()

    def test_clean_cell_phone_requires_at_least_one_of_cell_or_home(self):
        form = StudentProfileForm(student=self.student)
        form.cleaned_data = {"cell_phone": ""}
        form.data = {"home_phone": ""}
        with self.assertRaises(ValidationError):
            form.clean_cell_phone()

    def test_clean_cell_phone_rejects_invalid_value(self):
        form = StudentProfileForm(student=self.student)
        form.cleaned_data = {"cell_phone": "not-a-phone"}
        form.data = {"home_phone": ""}
        with self.assertRaises(ValidationError):
            form.clean_cell_phone()

    def test_clean_cell_phone_accepts_valid_us_number(self):
        form = StudentProfileForm(student=self.student)
        form.cleaned_data = {"cell_phone": "509-555-1234"}
        form.data = {"home_phone": ""}
        cleaned = form.clean_cell_phone()
        self.assertTrue(cleaned)

    def test_clean_parent_phone_returns_none_when_missing_and_not_required(self):
        form = StudentProfileForm(student=self.student)
        form.cleaned_data = {"parent_phone": ""}
        self.assertIsNone(form.clean_parent_phone())

    def test_clean_parent_phone_rejects_invalid_value(self):
        form = StudentProfileForm(student=self.student)
        form.cleaned_data = {"parent_phone": "not-a-phone"}
        with self.assertRaises(ValidationError):
            form.clean_parent_phone()

    def test_clean_parent_email_rejects_same_as_student_email(self):
        form = StudentProfileForm(student=self.student)
        form.cleaned_data = {"parent_email": "student@example.com", "email": "student@example.com"}
        with self.assertRaises(ValidationError):
            form.clean_parent_email()

    def test_clean_verify_student_ssn_mismatch_raises(self):
        form = StudentProfileForm(student=self.student)
        form.cleaned_data = {"ssn": "123", "verify_student_ssn": "321"}
        with self.assertRaises(ValidationError):
            form.clean_verify_student_ssn()

    def _build_storage_cleaned_data(self, form):
        """
        Build cleaned_data for every field backed by user/student/meta.

        StudentProfileForm.save() calls _save_fields_to_models() which blindly writes
        cleaned_data[name] into the target. This helper ensures we don't unintentionally
        overwrite fields with None/empty values.
        """
        cleaned = {}
        user = self.student.user
        for name, field in form.fields.items():
            target = getattr(field, "storage_target", None)
            if not target or target == "skip":
                continue

            path = getattr(field, "storage_path", None) or name

            if target == "user":
                cleaned[name] = getattr(user, path, "")
            elif target == "student":
                cleaned[name] = getattr(self.student, path, "")
            elif target == "meta":
                meta = self.student.meta or {}
                cleaned[name] = meta.get(path, "")

        return cleaned

    def test_save_updates_user_student_notifications_grade_and_last_reviewed(self):
        form = StudentProfileForm(student=self.student, data={"no_ssn": "on"})

        cleaned_data = self._build_storage_cleaned_data(form)
        cleaned_data.update(
            {
                "password": "Aa1!SecurePassword",
                "cell_phone_opt_in": True,
                "graduation_date": datetime.date(2026, 6, 1),
                # (not a field in the form currently, but included here for completeness)
                "us_citizen": None,
            }
        )

        form.cleaned_data = cleaned_data
        saved = form.save(commit=True)

        user = saved.user
        self.assertTrue(user.check_password("Aa1!SecurePassword"))

        saved.refresh_from_db()
        self.assertEqual(saved.notifications.get("cell_phone_opt_in"), True)
        self.assertEqual(saved.notifications.get("signed_no_ssn_waiver"), True)

        self.assertIsNotNone(saved.profile_last_reviewed)
        self.assertEqual(saved.profile_last_reviewed_id, self.term.id)

        # grade_level must always be a storable value the field can hold —
        # save() must never persist out-of-domain sentinels ('GRAD', '--')
        # that overflow the varchar(2) column.
        valid_grades = {code for code, _ in Student._meta.get_field("grade_level").choices}
        self.assertIn(saved.grade_level, valid_grades)

    def test_parent_guardian_type_field_labels_and_save_round_trip(self):
        form = StudentProfileForm(student=self.student)

        self.assertIn("parent_guardian_type", form.fields)
        self.assertEqual(form.fields["parent_guardian_type"].label, "Parent or Guardian Type")
        self.assertEqual(form.fields["parent_first_name"].label, "Parent/Guardian First Name")
        self.assertEqual(form.fields["parent_last_name"].label, "Parent/Guardian Last Name")
        self.assertEqual(form.fields["parent_email"].label, "Parent/Guardian Email")
        self.assertEqual(form.fields["parent_phone"].label, "Parent/Guardian Phone")

        cleaned_data = self._build_storage_cleaned_data(form)
        cleaned_data["parent_guardian_type"] = "Mother"
        form.cleaned_data = cleaned_data
        saved = form.save(commit=True)
        saved.refresh_from_db()
        self.assertEqual(saved.meta.get("parent_guardian_type"), "Mother")

        reloaded = StudentProfileForm(student=saved)
        self.assertEqual(reloaded.initial.get("parent_guardian_type"), "Mother")


class StudentProfileEditableFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name="student")

        cls.user = CustomUser.objects.create(
            username="student_editable",
            email="student_editable@example.com",
            first_name="Edit",
            last_name="Me",
            psid="",
            primary_phone="5095550000",
            secondary_phone="5095550001",
            address1="1 Test St",
            city="City",
            state="WA",
            postal_code="98901",
            country="US",
            date_of_birth=datetime.date(2015, 1, 15),
        )
        cls.student = Student.objects.create(
            user=cls.user,
            gender="m",
            notifications={"cell_phone_opt_in": "False"},
            meta={},
        )

        cls.sent_user = CustomUser.objects.create(
            username="student_sent",
            email="student_sent@example.com",
            first_name="Sent",
            last_name="Student",
            psid="R12345",
            primary_phone="5095550002",
            secondary_phone="5095550003",
            address1="2 Test St",
            city="City",
            state="WA",
            postal_code="98901",
            country="US",
            date_of_birth=datetime.date(2015, 1, 15),
        )
        cls.sent_student = Student.objects.create(
            user=cls.sent_user,
            gender="m",
            notifications={},
            meta={},
        )

    def test_editable_form_for_unsent_accepted_student_excludes_identity_and_password_fields(self):
        # An accepted student — sent to the SIS or not — gets exactly the
        # configured editable set. Being pre-SIS used to append first_name /
        # last_name / date_of_birth / ssn on top, overriding the admin's
        # exclusion of them; it no longer does. Signup mechanics are never
        # exposed either way.
        from cis.settings.student_profile import student_profile

        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {
                'editable_fields': list(tenant_editable_fields()),
                'locked_message': '',
                'editable_message': '',
                'profile_review_intro': '',
                'profile_review_template': '<div></div>',
            }},
        )
        # user.psid is "" -> is_sent_to_sis is False.
        Student.objects.filter(pk=self.student.pk).update(
            application_status='accepted')
        self.student.refresh_from_db()

        form = StudentEditableForm(student=self.student)

        # SSN and the signup mechanics are hidden outright, not read-only.
        self.assertNotIn("ssn", form.fields)
        self.assertNotIn("verify_student_ssn", form.fields)
        self.assertNotIn("password", form.fields)
        self.assertNotIn("confirm_password", form.fields)

        # Not in the configured set, so not editable — pre-SIS no longer widens
        # it. Still rendered, read-only, so the student can see what is on file.
        for name in ("first_name", "last_name", "date_of_birth"):
            self.assertIn(name, form.fields, name)
            self.assertIn(name, form.readonly_fields, name)
            self.assertTrue(form.fields[name].disabled, name)

    def test_editable_form_for_sent_student_does_not_include_identity_fields(self):
        from cis.settings.student_profile import student_profile

        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {
                'editable_fields': list(tenant_editable_fields()),
                'locked_message': '',
                'editable_message': '',
                'profile_review_intro': '',
                'profile_review_template': '<div></div>',
            }},
        )
        # sent_student.user.psid is "R12345" -> is_sent_to_sis is True.
        Student.objects.filter(pk=self.sent_student.pk).update(
            application_status='accepted')
        self.sent_student.refresh_from_db()

        form = StudentEditableForm(student=self.sent_student)

        # Present but read-only: not editable, still visible.
        for name in ("first_name", "last_name", "date_of_birth", "gender",
                     "preferred_name"):
            self.assertIn(name, form.fields, name)
            self.assertIn(name, form.readonly_fields, name)
        # SSN is the exception: hidden entirely rather than shown read-only.
        self.assertNotIn("ssn", form.fields)


class StudentProfileCISFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name="student")
        cls.user = CustomUser.objects.create(
            username="student_cis",
            email="student_cis@example.com",
            first_name="Cis",
            last_name="User",
            psid="R12345",
            primary_phone="5095550000",
            secondary_phone="5095550001",
            address1="1 Test St",
            city="City",
            state="WA",
            postal_code="98901",
            country="US",
            date_of_birth=datetime.date(2015, 1, 15),
        )
        cls.student = Student.objects.create(
            user=cls.user,
            gender="m",
            notifications={},
            meta={},
        )

    def test_cis_form_removes_ssn_and_password_fields_and_adds_admin_specific_fields(self):
        form = StudentCISForm(student=self.student)

        self.assertNotIn("verify_student_ssn", form.fields)
        self.assertNotIn("password", form.fields)
        self.assertNotIn("confirm_password", form.fields)

        self.assertIn("psid", form.fields)
        self.assertIn("alt_username", form.fields)
        self.assertIn("secondary_email", form.fields)

