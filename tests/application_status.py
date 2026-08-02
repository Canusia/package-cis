import datetime
import uuid
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.note import StudentNote
from cis.models.student import Student


def _make_user(**overrides):
    defaults = {
        "username": f"u-{uuid.uuid4()}",
        "email": f"{uuid.uuid4()}@example.com",
        "first_name": "Test",
        "last_name": "User",
        "psid": "-",
    }
    defaults.update(overrides)
    return CustomUser.objects.create(**defaults)


def _make_highschool():
    return HighSchool.objects.create(
        name=f"HS {uuid.uuid4()}",
        code=f"H{uuid.uuid4().hex[:6]}",
    )


class ApplicationStatusSignalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name="student")
        CustomUser.objects.get_or_create(
            username="cron",
            defaults={"email": "cron@example.com"},
        )

    def test_new_student_starts_as_draft(self):
        student = Student.objects.create(user=_make_user())
        self.assertEqual(student.application_status, "draft")

    def test_assigning_highschool_flips_draft_to_pending(self):
        student = Student.objects.create(user=_make_user())
        self.assertEqual(student.application_status, "draft")

        student.highschool = _make_highschool()
        student.save()

        student.refresh_from_db()
        self.assertEqual(student.application_status, "pending")

    def test_assigning_highschool_does_not_override_in_review(self):
        student = Student.objects.create(user=_make_user())
        student.application_status = "in_review"
        student.save(update_fields=["application_status"])

        student.highschool = _make_highschool()
        student.save()

        student.refresh_from_db()
        self.assertEqual(student.application_status, "in_review")

    @patch("cis.signals.students.registration_email")
    def test_matching_psid_flips_to_accepted_and_adds_note(self, reg_email_mock):
        reg_email_mock.from_db.return_value = {
            "id_verify_regex": r"^H\d{7}$",
            "send_id_assigned_email": "No",
        }
        user = _make_user()
        student = Student.objects.create(
            user=user,
            highschool=_make_highschool(),
        )
        student.refresh_from_db()
        self.assertEqual(student.application_status, "pending")

        user.psid = "H1234567"
        user.save()

        student.refresh_from_db()
        self.assertEqual(student.application_status, "accepted")
        self.assertTrue(
            StudentNote.objects.filter(
                student=student,
                note__icontains="SIS ID received",
            ).exists()
        )

    @patch("cis.signals.students.registration_email")
    def test_non_matching_psid_does_not_flip_to_accepted(self, reg_email_mock):
        reg_email_mock.from_db.return_value = {
            "id_verify_regex": r"^H\d{7}$",
            "send_id_assigned_email": "No",
        }
        user = _make_user()
        student = Student.objects.create(
            user=user,
            highschool=_make_highschool(),
        )

        user.psid = "XX-bogus"
        user.save()

        student.refresh_from_db()
        self.assertNotEqual(student.application_status, "accepted")


class UndupStudentsReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name="student")
        CustomUser.objects.get_or_create(
            username="cron",
            defaults={"email": "cron@example.com"},
        )

    def test_get_result_returns_only_pending_students(self):
        from cis.reports.undup_students import undup_students

        pending = Student.objects.create(
            user=_make_user(),
            highschool=_make_highschool(),
        )
        pending.refresh_from_db()
        self.assertEqual(pending.application_status, "pending")

        draft = Student.objects.create(user=_make_user())

        in_review = Student.objects.create(
            user=_make_user(),
            highschool=_make_highschool(),
        )
        in_review.application_status = "in_review"
        in_review.save(update_fields=["application_status"])

        results = list(undup_students().get_result({}))
        ids = {s.id for s in results}

        self.assertIn(pending.id, ids)
        self.assertNotIn(draft.id, ids)
        self.assertNotIn(in_review.id, ids)

    def test_mark_as_sent_flips_to_in_review_and_adds_note(self):
        from cis.models.section import StudentRegistration
        from cis.reports.undup_students import undup_students

        student = Student.objects.create(
            user=_make_user(),
            highschool=_make_highschool(),
        )
        student.refresh_from_db()

        form = undup_students()
        with patch.object(
            StudentRegistration.objects, "filter"
        ) as mock_filter:
            mock_filter.return_value.values.return_value.annotate.return_value.values_list.return_value = [
                (student.id, 1)
            ]
            with patch(
                "cis.reports.undup_students.PrivateMediaStorage"
            ) as storage_cls:
                storage = storage_cls.return_value
                storage.save.side_effect = lambda p, c: p
                storage.url.side_effect = lambda p: f"/media/{p}"

                task = type("T", (), {"id": uuid.uuid4()})()
                form.run(
                    task,
                    {
                        "mark_as_sent": ["1"],
                        "send_to_slate": ["0"],
                    },
                )

        student.refresh_from_db()
        self.assertEqual(student.application_status, "in_review")
        self.assertIsNotNone(student.sis_sent_on)
        self.assertTrue(
            StudentNote.objects.filter(
                student=student,
                note__icontains="sent to SIS",
            ).exists()
        )

    def test_send_to_slate_returns_actual_exported_count(self):
        """send_to_slate=1 + mark_as_sent=1: run() must report the number of
        records actually exported, not 0. Regression: it returned
        records.count(), which re-queried the application_status='pending'
        filter AFTER the loop flipped every exported row to 'in_review',
        so the count came back 0 (export_student_data logged 'Sent 0 to ...')."""
        import io

        from cis.models.section import StudentRegistration
        from cis.reports.undup_students import undup_students

        students = [
            Student.objects.create(user=_make_user(), highschool=_make_highschool())
            for _ in range(3)
        ]
        for student in students:
            student.refresh_from_db()
            self.assertEqual(student.application_status, "pending")

        form = undup_students()
        sent_stream = io.StringIO()

        with patch.object(StudentRegistration.objects, "filter") as mock_filter:
            mock_filter.return_value.values.return_value.annotate.return_value.values_list.return_value = []
            with patch(
                "cis.settings.student_exporter.student_exporter"
            ) as exporter_cfg, patch("cis.utils.sftp_connect") as sftp_connect_mock:
                exporter_cfg.from_db.return_value = {
                    "path_to_file": "students_{{yyyy}}.csv",
                    "host_name": "h",
                    "port": 22,
                    "username": "u",
                    "password": "p",
                    "private_key": "",
                }
                sftp = type("Sftp", (), {"open": lambda self, name, mode: sent_stream})()
                sftp_connect_mock.return_value = (object(), sftp)

                task = type("T", (), {"id": uuid.uuid4()})()
                count, path = form.run(
                    task,
                    {
                        "mark_as_sent": ["1"],
                        "send_to_slate": ["1"],
                    },
                )

        self.assertEqual(count, 3)
        # The mutation really happened, so records.count() would have said 0.
        for student in students:
            student.refresh_from_db()
            self.assertEqual(student.application_status, "in_review")

    def test_export_contact_type_and_parent_guardian_headers(self):
        import csv
        import io

        from cis.models.section import StudentRegistration
        from cis.reports.undup_students import undup_students

        student = Student.objects.create(
            user=_make_user(),
            highschool=_make_highschool(),
            account_verified=True,
            meta={"parent_guardian_type": "Legal Guardian"},
        )

        form = undup_students()
        self.assertEqual(
            form._value_for_field(student, "export_contact_type", timezone.now()),
            "Legal Guardian",
        )

        captured = {}

        def _capture_save(path, content):
            captured["content"] = content.read().decode("utf-8")
            return path

        with patch.object(StudentRegistration.objects, "filter") as mock_filter:
            mock_filter.return_value.values.return_value.annotate.return_value.values_list.return_value = [
                (student.id, 0)
            ]
            with patch(
                "cis.reports.undup_students.PrivateMediaStorage"
            ) as storage_cls:
                storage = storage_cls.return_value
                storage.save.side_effect = _capture_save
                storage.url.side_effect = lambda p: f"/media/{p}"

                task = type("T", (), {"id": uuid.uuid4()})()
                form.run(
                    task,
                    {
                        "mark_as_sent": ["0"],
                        "send_to_slate": ["0"],
                    },
                )

        rows = list(csv.reader(io.StringIO(captured["content"])))
        headers = rows[0]
        self.assertIn("Contact type", headers)
        self.assertIn("Parent First Name", headers)
        self.assertIn("Parent Last Name", headers)
        self.assertIn("Parent Email", headers)

        contact_type_index = headers.index("Contact type")
        self.assertEqual(rows[1][contact_type_index], "Legal Guardian")
