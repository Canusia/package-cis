import csv
import datetime
import io
import uuid
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone

from cis.models.customuser import CustomUser
from cis.models.settings import Setting
from cis.models.student import Student
from cis.reports.student_profile_dynamic_export import (
    _widget_is_effectively_hidden,
    student_profile_dynamic_export,
)
from cis.forms.student_profile import StudentProfileForm


class _FakeStorage:
    last_path = None
    last_content = None

    def save(self, path, content):
        _FakeStorage.last_path = path
        _FakeStorage.last_content = content.read().decode("utf-8")
        return path

    def url(self, path):
        return f"/media/{path}"


class StudentProfileDynamicExportReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name="student")

        from django.conf import settings

        prefix = getattr(settings, "CAMPUS_CODE_PREFIX", "TEST")
        # Field wording lives on the student_profile setting as a native dict;
        # the legacy signup.form_field_messages fallback is covered by
        # cis.tests.test_profile_field_messages.
        Setting.objects.create(
            key=f"{prefix}_student_profile",
            value={
                "field_messages": {
                    "first_name": {"label": "<b>Student First Name</b>"},
                }
            },
        )

        cls.user_one = CustomUser.objects.create(
            username="report_student_one",
            email="student-one@example.com",
            first_name="Avi",
            last_name="One",
            address1="123 Permanent St",
            city="Syracuse",
            state="NY",
            postal_code="13224",
            country="US",
        )
        cls.user_two = CustomUser.objects.create(
            username="report_student_two",
            email="student-two@example.com",
            first_name="Chris",
            last_name="Two",
            address1="456 Permanent St",
            city="Syracuse",
            state="NY",
            postal_code="13224",
            country="US",
        )

        cls.student_one = Student.objects.create(
            user=cls.user_one,
            gender="m",
            preferred_name="Ace",
            meta={"mailing_address": "PO Box 10"},
        )
        cls.student_two = Student.objects.create(
            user=cls.user_two,
            gender="f",
            preferred_name="C",
            meta={"mailing_address": "PO Box 20"},
        )

        created_one = timezone.make_aware(datetime.datetime(2026, 4, 10, 12, 0, 0))
        created_two = timezone.make_aware(datetime.datetime(2026, 4, 15, 12, 0, 0))
        CustomUser.objects.filter(pk=cls.user_one.pk).update(created_at=created_one)
        CustomUser.objects.filter(pk=cls.user_two.pk).update(created_at=created_two)

    def _run_report_and_read_rows(self, created_on, created_until):
        report = student_profile_dynamic_export()
        task = type("Task", (), {"id": uuid.uuid4()})()

        _FakeStorage.last_content = None
        _FakeStorage.last_path = None

        with patch(
            "cis.reports.student_profile_dynamic_export.PrivateMediaStorage",
            _FakeStorage,
        ):
            report.run(
                task,
                {"created_on": [created_on], "created_until": [created_until]},
            )

        self.assertIsNotNone(_FakeStorage.last_content)
        reader = csv.reader(io.StringIO(_FakeStorage.last_content))
        return list(reader)

    def test_uses_oldest_created_for_start_and_today_for_until(self):
        report = student_profile_dynamic_export()

        self.assertEqual(report.fields["created_on"].initial, datetime.date(2026, 4, 10))
        self.assertEqual(report.fields["created_until"].initial, timezone.localdate())
        self.assertIn("04/10/2026", report.fields["created_on"].help_text)
        self.assertIn("oldest student", report.fields["created_on"].help_text.lower())

    def test_includes_only_persisted_fields_and_uses_dynamic_labels(self):
        rows = self._run_report_and_read_rows("2026-04-01", "2026-04-30")
        headers = rows[0]

        self.assertIn("Student First Name", headers)
        self.assertIn("Preferred First Name", headers)
        self.assertNotIn("Password", headers)
        self.assertNotIn("Signature", headers)

    def test_hidden_input_fields_are_excluded_from_export_columns(self):
        report = student_profile_dynamic_export()
        exported = {f["name"] for f in report._form_fields_for_export()}
        form = StudentProfileForm(student=None, request=None)
        for field_name, field in form.fields.items():
            target = getattr(field, "storage_target", None)
            if target not in ("user", "student", "meta"):
                continue
            if _widget_is_effectively_hidden(field.widget):
                self.assertNotIn(field_name, exported)

    def test_created_until_is_inclusive(self):
        rows = self._run_report_and_read_rows("2026-04-15", "2026-04-15")

        self.assertEqual(len(rows), 2)
        headers = rows[0]
        first_name_index = headers.index("Student First Name")
        self.assertEqual(rows[1][first_name_index], "Chris")

    def test_date_range_excludes_records_outside_window(self):
        before = self._run_report_and_read_rows("2026-04-01", "2026-04-09")
        after = self._run_report_and_read_rows("2026-04-16", "2026-04-30")
        spanning = self._run_report_and_read_rows("2026-04-10", "2026-04-15")

        self.assertEqual(len(before), 1)
        self.assertEqual(len(after), 1)
        self.assertEqual(len(spanning), 3)

        first_name_index = spanning[0].index("Student First Name")
        names = {row[first_name_index] for row in spanning[1:]}
        self.assertEqual(names, {"Avi", "Chris"})

    def test_exports_user_student_and_meta_values(self):
        rows = self._run_report_and_read_rows("2026-04-01", "2026-04-30")
        headers = rows[0]

        first_name_index = headers.index("Student First Name")
        preferred_name_index = headers.index("Preferred First Name")
        mailing_address_index = headers.index("Mailing Address")

        self.assertEqual(rows[1][first_name_index], "Avi")
        self.assertEqual(rows[1][preferred_name_index], "Ace")
        self.assertEqual(rows[1][mailing_address_index], "PO Box 10")
