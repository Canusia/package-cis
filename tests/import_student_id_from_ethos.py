import uuid
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

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


def _make_hs():
    return HighSchool.objects.create(
        name=f"HS {uuid.uuid4()}",
        code=f"H{uuid.uuid4().hex[:6]}",
    )


def _in_review_student():
    student = Student.objects.create(user=_make_user(), highschool=_make_hs())
    student.application_status = 'in_review'
    student.save(update_fields=['application_status'])
    return student


class ImportStudentIdFromEthosCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name="student")
        CustomUser.objects.get_or_create(
            username="cron",
            defaults={"email": "cron@example.com"},
        )

    def _active_cfg(self):
        return {
            'is_active': 'Yes',
            'notification_list': '',
            'path_to_results_file': 'results_{{yyyy}}{{mm}}{{dd}}.csv',
        }

    @patch("cis.management.commands.import_student_id_from_ethos.PrivateMediaStorage")
    @patch("myce_tenant_configs.services.ethos_identity.lookup_ethos_person_for_student")
    @patch("myce_tenant_configs.services.ethos_identity.get_alt_credential_type_id")
    @patch("cis.management.commands.import_student_id_from_ethos.student_id_importer")
    def test_matched_student_updated_no_match_skipped(
        self, settings_mock, type_id_mock, lookup_mock, storage_cls
    ):
        settings_mock.from_db.return_value = self._active_cfg()
        type_id_mock.return_value = "alt-type-guid"
        storage_cls.return_value.save.side_effect = lambda p, c: p

        matched = _in_review_student()
        nomatch = _in_review_student()
        draft = Student.objects.create(user=_make_user())

        def fake_lookup(student, type_id=None):
            if student.id == matched.id:
                return {
                    "id": "12345678-1234-1234-1234-123456789abc",
                    "bannerid": "H7654321",
                    "username": "jsmith",
                }
            return None

        lookup_mock.side_effect = fake_lookup

        with patch(
            "cis.management.commands.import_student_id_from_ethos.cron_task_done"
        ) as done_mock:
            call_command("import_student_id_from_ethos", time="2026-04-21 12:00:00")

        matched.refresh_from_db()
        self.assertEqual(str(matched.sis_id), "12345678-1234-1234-1234-123456789abc")
        self.assertEqual(matched.user.psid, "H7654321")
        self.assertEqual(matched.user.username, "jsmith")
        self.assertTrue(
            StudentNote.objects.filter(
                student=matched, note__icontains="SIS ID lookup via Ethos"
            ).exists()
        )

        nomatch.refresh_from_db()
        self.assertEqual(nomatch.application_status, "in_review")
        self.assertIsNone(nomatch.sis_id)

        # draft student was never looked up
        for call in lookup_mock.call_args_list:
            self.assertNotEqual(call.args[0].id, draft.id)

        done_mock.send.assert_called_once()
        summary = done_mock.send.call_args.kwargs["summary"]
        self.assertIn("Updated: 1", summary)
        self.assertIn("No match in Ethos: 1", summary)
        self.assertIn("Checked 2 students", summary)

    @patch("myce_tenant_configs.services.ethos_identity.get_alt_credential_type_id")
    @patch("cis.management.commands.import_student_id_from_ethos.student_id_importer")
    def test_missing_type_id_aborts_with_summary(self, settings_mock, type_id_mock):
        settings_mock.from_db.return_value = self._active_cfg()
        type_id_mock.return_value = None

        _in_review_student()

        with patch(
            "cis.management.commands.import_student_id_from_ethos.cron_task_done"
        ) as done_mock:
            call_command("import_student_id_from_ethos", time="2026-04-21 12:00:00")

        done_mock.send.assert_called_once()
        summary = done_mock.send.call_args.kwargs["summary"]
        self.assertIn("Aborted", summary)

    @patch("cis.management.commands.import_student_id_from_ethos.student_id_importer")
    def test_inactive_config_returns_without_running(self, settings_mock):
        settings_mock.from_db.return_value = {'is_active': 'No'}

        student = _in_review_student()

        with patch(
            "myce_tenant_configs.services.ethos_identity.lookup_ethos_person_for_student"
        ) as lookup_mock:
            call_command("import_student_id_from_ethos", time="2026-04-21 12:00:00")
            lookup_mock.assert_not_called()

        student.refresh_from_db()
        self.assertEqual(student.application_status, "in_review")
