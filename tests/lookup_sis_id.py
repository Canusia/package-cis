import json
import uuid
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.http import QueryDict
from django.test import RequestFactory, TestCase

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.note import StudentNote
from cis.models.student import Student
from cis.views.student import lookup_sis_id


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


def _post(student_id, actor, **extra):
    rf = RequestFactory()
    req = rf.post("/ce/student_bulk_actions/")
    qd = QueryDict(mutable=True)
    qd.setlist("ids[]", [str(student_id)])
    for k, v in extra.items():
        qd[k] = v
    req.POST = qd
    req.user = actor
    return req


class LookupSisIdActionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name="student")
        CustomUser.objects.get_or_create(
            username="cron",
            defaults={"email": "cron@example.com"},
        )

    def _settings_with_guid(self, guid="alt-type-guid"):
        return {"guids": json.dumps({"alternativeCredentials": guid})}

    @patch("myce_tenant_configs.services.ethos_identity.lookup_ethos_person_for_student")
    @patch("myce_tenant_configs.services.ethos_identity.get_alt_credential_type_id")
    def test_lookup_returns_modal_without_saving(self, type_id_mock, lookup_mock):
        type_id_mock.return_value = "alt-type-guid"
        lookup_mock.return_value = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "bannerid": "H9999999",
            "username": "jdoe",
            "other_email": None,
            "raw": {},
        }

        actor = _make_user()
        student = Student.objects.create(
            user=_make_user(),
            highschool=_make_highschool(),
        )
        student.refresh_from_db()
        self.assertEqual(student.application_status, "pending")

        resp = lookup_sis_id(_post(student.id, actor))
        body = json.loads(resp.content)
        self.assertEqual(body["outcome"], "modal")
        self.assertIn("H9999999", body["html"])
        self.assertIn("jdoe", body["html"])
        self.assertIn("12345678-1234-1234-1234-123456789abc", body["html"])

        student.refresh_from_db()
        self.assertIsNone(student.sis_id)
        self.assertEqual(student.user.psid, "-")
        self.assertEqual(student.application_status, "pending")

    def test_confirmed_save_updates_identity_and_flips_status(self):
        actor = _make_user()
        student = Student.objects.create(
            user=_make_user(),
            highschool=_make_highschool(),
        )
        # Only an in_review application flips to accepted on Ethos confirm
        # (assigning a highschool leaves it 'pending'); mark_as_sent moves it
        # to in_review before the SIS ID lookup is confirmed.
        student.application_status = "in_review"
        student.save(update_fields=["application_status"])
        student.refresh_from_db()

        resp = lookup_sis_id(_post(
            student.id, actor,
            action_confirmed="1",
            new_sis_id="12345678-1234-1234-1234-123456789abc",
            new_psid="H9999999",
            new_username="jdoe",
        ))
        body = json.loads(resp.content)
        self.assertEqual(body["outcome"], "call")

        student.refresh_from_db()
        self.assertEqual(str(student.sis_id), "12345678-1234-1234-1234-123456789abc")
        self.assertEqual(student.user.psid, "H9999999")
        self.assertEqual(student.user.username, "jdoe")
        self.assertEqual(student.application_status, "accepted")
        self.assertTrue(
            StudentNote.objects.filter(
                student=student, note__icontains="SIS ID lookup via Ethos"
            ).exists()
        )

    def test_confirmed_save_with_no_changes_returns_info(self):
        actor = _make_user()
        sid = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
        user = _make_user(psid="H1234567", username="already")
        student = Student.objects.create(
            user=user,
            highschool=_make_highschool(),
            sis_id=sid,
        )

        resp = lookup_sis_id(_post(
            student.id, actor,
            action_confirmed="1",
            new_sis_id=str(sid),
            new_psid="H1234567",
            new_username="already",
        ))
        body = json.loads(resp.content)
        self.assertEqual(body["outcome"], "alert")
        self.assertEqual(body["status"], "info")

    @patch("myce_tenant_configs.services.ethos_identity.lookup_ethos_person_for_student")
    @patch("myce_tenant_configs.services.ethos_identity.get_alt_credential_type_id")
    def test_no_match_returns_warning(self, type_id_mock, lookup_mock):
        type_id_mock.return_value = "alt-type-guid"
        lookup_mock.return_value = None

        actor = _make_user()
        student = Student.objects.create(
            user=_make_user(),
            highschool=_make_highschool(),
        )

        resp = lookup_sis_id(_post(student.id, actor))
        body = json.loads(resp.content)
        self.assertEqual(body["outcome"], "alert")
        self.assertEqual(body["status"], "warning")

    @patch("myce_tenant_configs.services.ethos_identity.get_alt_credential_type_id")
    def test_missing_guid_returns_error(self, type_id_mock):
        type_id_mock.return_value = None

        actor = _make_user()
        student = Student.objects.create(user=_make_user())

        resp = lookup_sis_id(_post(student.id, actor))
        body = json.loads(resp.content)
        self.assertEqual(body["outcome"], "alert")
        self.assertEqual(body["status"], "error")
