"""student_profile_dynamic_export against cis.tests.fake_tenant
(package-cis#57): columns come from the tenant form, labels from the
student_profile setting."""
import csv
import datetime
import io
import uuid
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.utils import timezone

from cis.forms import student_profile as profile_mod
from cis.models.customuser import CustomUser
from cis.models.settings import Setting
from cis.models.student import Student
from cis.reports.student_profile_dynamic_export import (
    _widget_is_effectively_hidden,
    student_profile_dynamic_export,
)

FAKE_TENANT = 'cis.tests.fake_tenant'


class _FakeStorage:
    last_path = None
    last_content = None

    def save(self, path, content):
        _FakeStorage.last_path = path
        _FakeStorage.last_content = content.read().decode("utf-8")
        return path

    def url(self, path):
        return f"/media/{path}"


@override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
class StudentProfileDynamicExportReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name="student")

        prefix = getattr(settings, "CAMPUS_CODE_PREFIX", "TEST")
        Setting.objects.update_or_create(
            key=f"{prefix}_student_profile",
            defaults={"value": {
                "field_messages": {
                    "first_name": {"label": "<b>Relabelled Given Name</b>"},
                }
            }},
        )

        cls.user_one = CustomUser.objects.create(
            username="report_student_one",
            email="student-one@example.com",
            first_name="Avi",
            last_name="One",
        )
        cls.user_two = CustomUser.objects.create(
            username="report_student_two",
            email="student-two@example.com",
            first_name="Chris",
            last_name="Two",
        )
        Student.objects.create(
            user=cls.user_one, preferred_name="Ace",
            meta={"fake_meta_note": "note one", "fake_hidden_code": "H1"},
        )
        Student.objects.create(
            user=cls.user_two, preferred_name="C",
            meta={"fake_meta_note": "note two"},
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
        return list(csv.reader(io.StringIO(_FakeStorage.last_content)))

    def test_uses_oldest_created_for_start_and_today_for_until(self):
        report = student_profile_dynamic_export()
        self.assertEqual(report.fields["created_on"].initial, datetime.date(2026, 4, 10))
        self.assertEqual(report.fields["created_until"].initial, timezone.localdate())
        self.assertIn("04/10/2026", report.fields["created_on"].help_text)
        self.assertIn("oldest student", report.fields["created_on"].help_text.lower())

    def test_includes_only_persisted_fields_and_uses_dynamic_labels(self):
        headers = self._run_report_and_read_rows("2026-04-01", "2026-04-30")[0]
        self.assertIn("Relabelled Given Name", headers)
        self.assertIn("Fake Nickname", headers)
        self.assertIn("Fake Meta Note", headers)
        self.assertNotIn("Password", headers)
        self.assertNotIn("Verify SSN", headers)

    def test_hidden_input_fields_are_excluded_from_export_columns(self):
        exported = {f["name"] for f in
                    student_profile_dynamic_export()._form_fields_for_export()}
        self.assertNotIn("fake_hidden_code", exported)
        form = profile_mod.StudentProfileForm(student=None, request=None)
        for field_name, field in form.fields.items():
            if getattr(field, "storage_target", None) not in ("user", "student", "meta"):
                continue
            if _widget_is_effectively_hidden(field.widget):
                self.assertNotIn(field_name, exported)

    def test_created_until_is_inclusive(self):
        rows = self._run_report_and_read_rows("2026-04-15", "2026-04-15")
        self.assertEqual(len(rows), 2)
        index = rows[0].index("Relabelled Given Name")
        self.assertEqual(rows[1][index], "Chris")

    def test_date_range_excludes_records_outside_window(self):
        before = self._run_report_and_read_rows("2026-04-01", "2026-04-09")
        after = self._run_report_and_read_rows("2026-04-16", "2026-04-30")
        spanning = self._run_report_and_read_rows("2026-04-10", "2026-04-15")

        self.assertEqual(len(before), 1)
        self.assertEqual(len(after), 1)
        self.assertEqual(len(spanning), 3)

        index = spanning[0].index("Relabelled Given Name")
        self.assertEqual({row[index] for row in spanning[1:]}, {"Avi", "Chris"})

    def test_exports_user_student_and_meta_values(self):
        rows = self._run_report_and_read_rows("2026-04-01", "2026-04-30")
        headers = rows[0]
        by_name = {row[headers.index("Relabelled Given Name")]: row for row in rows[1:]}
        avi = by_name["Avi"]
        self.assertEqual(avi[headers.index("Fake Nickname")], "Ace")
        self.assertEqual(avi[headers.index("Fake Meta Note")], "note one")
