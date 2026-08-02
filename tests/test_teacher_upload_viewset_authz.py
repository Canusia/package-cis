"""Authorization tests for TeacherUploadViewSet (pentest finding PT-11).

The /ce/api/teacher-uploads endpoint must not leak other instructors' upload
metadata or pre-signed private media URLs:

  * instructor   -> only their own uploads (client teacher_id is ignored)
  * highschool_admin -> only uploads for teachers in their high schools
  * ce (CE admin) -> full access, may target any teacher_id or list all
  * any other role -> no access (403)
"""
from unittest import mock

from django.http import HttpResponse
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherUpload
from cis.models.highschool_administrator import (
    HSAdministrator, HSPosition, HSAdministratorPosition,
)

User = get_user_model()


def _upload_for(teacher):
    """Create a TeacherUpload with a tiny in-memory file (no real S3 round-trip)."""
    return TeacherUpload.objects.create(
        teacher=teacher,
        media_type='Resume',
        media=SimpleUploadedFile('r.txt', b'data', content_type='text/plain'),
    )


class _TeacherUploadAuthzData:
    """Shared fixtures + helpers for the teacher-uploads authz test classes."""

    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    @classmethod
    def setUpTestData(cls):
        for name in ('ce', 'instructor', 'highschool_admin', 'student'):
            Group.objects.get_or_create(name=name)

        # Two high schools in different "tenants".
        cls.hs_a = HighSchool.objects.create(name='HS Alpha')
        cls.hs_b = HighSchool.objects.create(name='HS Beta')

        # Teacher 1 (the instructor we authenticate as) at HS Alpha.
        u1 = User.objects.create_user(
            username='inst1', email='inst1@example.com', password='x',
            first_name='Ina', last_name='One',
        )
        u1.groups.add(Group.objects.get(name='instructor'))
        cls.teacher1 = Teacher.objects.create(user=u1)
        TeacherHighSchool.objects.create(
            teacher=cls.teacher1, highschool=cls.hs_a, status='In the Program',
        )
        cls.instructor_user = u1
        cls.upload1 = _upload_for(cls.teacher1)

        # Teacher 2 at HS Alpha (same school as teacher1 / the HS admin scope).
        u2 = User.objects.create_user(
            username='inst2', email='inst2@example.com', password='x',
            first_name='Ivo', last_name='Two',
        )
        cls.teacher2 = Teacher.objects.create(user=u2)
        TeacherHighSchool.objects.create(
            teacher=cls.teacher2, highschool=cls.hs_a, status='In the Program',
        )
        cls.upload2 = _upload_for(cls.teacher2)

        # Teacher 3 at HS Beta (a DIFFERENT school — out of HS-Alpha-admin scope).
        u3 = User.objects.create_user(
            username='inst3', email='inst3@example.com', password='x',
            first_name='Ike', last_name='Three',
        )
        cls.teacher3 = Teacher.objects.create(user=u3)
        TeacherHighSchool.objects.create(
            teacher=cls.teacher3, highschool=cls.hs_b, status='In the Program',
        )
        cls.upload3 = _upload_for(cls.teacher3)

        # Highschool admin for HS Alpha only.
        hsa_user = User.objects.create_user(
            username='hsadmin_a', email='hsadmin_a@example.com', password='x',
            first_name='Hank', last_name='Admin',
        )
        hsa_user.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa_user
        hsadmin = HSAdministrator.objects.create(user=hsa_user)
        position = HSPosition.objects.create(name='Principal')
        HSAdministratorPosition.objects.create(
            hsadmin=hsadmin, highschool=cls.hs_a, position=position,
            status='Active',
        )

        # CE administrator.
        ce_user = User.objects.create_user(
            username='ce1', email='ce1@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce_user.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce_user

        # A role with no business here.
        stud_user = User.objects.create_user(
            username='stud1', email='stud1@example.com', password='x',
            first_name='Sam', last_name='Student',
        )
        stud_user.groups.add(Group.objects.get(name='student'))
        cls.student_user = stud_user

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    @staticmethod
    def _ids(resp):
        payload = resp.json()
        rows = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        return {r['id'] for r in rows}


class TeacherUploadViewSetAuthzTests(_TeacherUploadAuthzData, TestCase):
    # --- instructor ---------------------------------------------------------
    def test_instructor_sees_only_own_uploads(self):
        self.client.force_login(self.instructor_user)
        resp = self.client.get('/ce/api/teacher-uploads/?format=json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), {str(self.upload1.id)})

    def test_instructor_teacher_id_param_is_ignored(self):
        # Trying to target another teacher must NOT widen the result set.
        self.client.force_login(self.instructor_user)
        resp = self.client.get(
            f'/ce/api/teacher-uploads/?format=json&teacher_id={self.teacher2.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), {str(self.upload1.id)})

    def test_instructor_cannot_retrieve_other_upload(self):
        self.client.force_login(self.instructor_user)
        resp = self.client.get(
            f'/ce/api/teacher-uploads/{self.upload2.id}/?format=json')
        self.assertEqual(resp.status_code, 404)

    def test_instructor_excludes_same_highschool_sibling_upload(self):
        # teacher1 (the caller) and teacher2 both sit at HS Alpha. Sharing a
        # high school must NOT widen an instructor's visibility — they see
        # only THEIR own upload, never a same-school colleague's. (PT-11)
        self.client.force_login(self.instructor_user)
        resp = self.client.get('/ce/api/teacher-uploads/?format=json')
        self.assertEqual(resp.status_code, 200)
        ids = self._ids(resp)
        self.assertIn(str(self.upload1.id), ids)
        self.assertNotIn(str(self.upload2.id), ids)
        self.assertNotIn(str(self.upload3.id), ids)

    # --- highschool_admin ---------------------------------------------------
    def test_hsadmin_sees_uploads_in_their_highschool_only(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get('/ce/api/teacher-uploads/?format=json')
        self.assertEqual(resp.status_code, 200)
        # teacher1 + teacher2 are at HS Alpha; teacher3 is at HS Beta.
        self.assertEqual(
            self._ids(resp), {str(self.upload1.id), str(self.upload2.id)})

    def test_hsadmin_cannot_retrieve_out_of_scope_upload(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(
            f'/ce/api/teacher-uploads/{self.upload3.id}/?format=json')
        self.assertEqual(resp.status_code, 404)

    # --- ce admin -----------------------------------------------------------
    def test_ce_sees_all_uploads(self):
        self.client.force_login(self.ce_user)
        resp = self.client.get('/ce/api/teacher-uploads/?format=json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self._ids(resp),
            {str(self.upload1.id), str(self.upload2.id), str(self.upload3.id)},
        )

    def test_ce_can_filter_by_arbitrary_teacher_id(self):
        self.client.force_login(self.ce_user)
        resp = self.client.get(
            f'/ce/api/teacher-uploads/?format=json&teacher_id={self.teacher3.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), {str(self.upload3.id)})

    # --- unauthorized role --------------------------------------------------
    def test_student_role_is_forbidden(self):
        self.client.force_login(self.student_user)
        resp = self.client.get('/ce/api/teacher-uploads/?format=json')
        self.assertEqual(resp.status_code, 403)

    # --- serializer PII minimization (Task 3) -------------------------------
    @staticmethod
    def _rows(resp):
        payload = resp.json()
        return payload['results'] if isinstance(payload, dict) and 'results' in payload else payload

    def test_row_exposes_ui_fields(self):
        """The keys the consuming DataTables render must still be present."""
        self.client.force_login(self.instructor_user)
        resp = self.client.get('/ce/api/teacher-uploads/?format=json')
        self.assertEqual(resp.status_code, 200)
        rows = self._rows(resp)
        self.assertTrue(rows)
        row = rows[0]
        for key in ('id', 'media_type', 'description', 'media', 'uploaded_on'):
            self.assertIn(key, row)
        # Slim teacher stub: id + non-PII display name only.
        self.assertIn('teacher', row)
        self.assertEqual(set(row['teacher'].keys()), {'id', 'name'})

    def test_row_omits_teacher_user_pii(self):
        """Nested teacher.user PII must no longer travel in the payload."""
        self.client.force_login(self.instructor_user)
        resp = self.client.get('/ce/api/teacher-uploads/?format=json')
        self.assertEqual(resp.status_code, 200)
        row = self._rows(resp)[0]
        teacher = row['teacher']
        # The old full nesting is gone: no nested user object at all.
        self.assertNotIn('user', teacher)
        # And none of the dropped PII keys leak at the teacher level either.
        for pii_key in (
            'primary_phone', 'secondary_phone', 'alt_phone',
            'email', 'alt_email', 'secondary_email',
            'address1', 'city', 'state', 'postal_code',
            'date_of_birth', 'first_name', 'last_name',
        ):
            self.assertNotIn(pii_key, teacher)

    # --- no pre-signed media URL in list (Task 4) ---------------------------
    def test_media_field_is_download_action_url_not_presigned(self):
        """media must be the relative download-action URL, not a signed S3 URL."""
        self.client.force_login(self.instructor_user)
        resp = self.client.get('/ce/api/teacher-uploads/?format=json')
        self.assertEqual(resp.status_code, 200)
        row = self._rows(resp)[0]
        media = row['media']
        self.assertEqual(
            media,
            f'/ce/api/teacher-uploads/{self.upload1.id}/download/',
        )
        # No pre-signed storage URL markers anywhere in the payload.
        body = resp.content.decode()
        self.assertNotIn('X-Amz-Signature', body)
        self.assertNotIn('AWSAccessKeyId', body)
        self.assertNotIn('amazonaws.com', body)


# Patch the file-streaming boundary so download authz tests assert the
# access-control outcome (200 / 404 / 403) without a live S3 GET. get_object()
# (and thus the role-scope 404) runs before FileResponse is ever reached.
def _fake_file_response(*args, **kwargs):
    return HttpResponse(b'ok')


@mock.patch('cis.views.teacher.FileResponse', side_effect=_fake_file_response)
class TeacherUploadDownloadAuthzTests(_TeacherUploadAuthzData, TestCase):
    """Download-action authorization mirrors the list/detail matrix (PT-11)."""

    def _download(self, upload):
        return self.client.get(
            f'/ce/api/teacher-uploads/{upload.id}/download/')

    def test_instructor_downloads_own(self, _fr):
        self.client.force_login(self.instructor_user)
        self.assertEqual(self._download(self.upload1).status_code, 200)

    def test_instructor_cannot_download_other(self, _fr):
        self.client.force_login(self.instructor_user)
        self.assertEqual(self._download(self.upload2).status_code, 404)

    def test_hsadmin_downloads_in_scope(self, _fr):
        self.client.force_login(self.hsadmin_user)
        self.assertEqual(self._download(self.upload2).status_code, 200)

    def test_hsadmin_cannot_download_out_of_scope(self, _fr):
        self.client.force_login(self.hsadmin_user)
        self.assertEqual(self._download(self.upload3).status_code, 404)

    def test_ce_downloads_any(self, _fr):
        self.client.force_login(self.ce_user)
        self.assertEqual(self._download(self.upload3).status_code, 200)

    def test_student_download_is_forbidden(self, _fr):
        self.client.force_login(self.student_user)
        self.assertEqual(self._download(self.upload1).status_code, 403)


class TeacherUploadTeacherIdUuidGuardTests(TestCase):
    """A non-UUID teacher_id must not 500 (ValidationError). CE/hsadmin get an
    empty result; the instructor branch still ignores teacher_id and returns
    the instructor's own uploads."""

    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    @classmethod
    def setUpTestData(cls):
        for name in ('ce', 'highschool_admin', 'instructor'):
            Group.objects.get_or_create(name=name)

        ce = User.objects.create_user(
            username='ce_tid', email='ce_tid@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce

        hsa = User.objects.create_user(
            username='hsa_tid', email='hsa_tid@example.com', password='x',
            first_name='Hank', last_name='Admin',
        )
        hsa.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa

        inst_user = User.objects.create_user(
            username='inst_tid', email='inst_tid@example.com', password='x',
            first_name='Ina', last_name='Structor',
        )
        inst_user.groups.add(Group.objects.get(name='instructor'))
        cls.instructor_user = inst_user
        cls.teacher = Teacher.objects.create(user=inst_user)
        cls.own_upload = TeacherUpload.objects.create(
            teacher=cls.teacher,
            media_type='Resume',
            media=SimpleUploadedFile('r.txt', b'data', content_type='text/plain'),
        )

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    def test_ce_malformed_teacher_id_returns_empty_not_500(self):
        self.client.force_login(self.ce_user)
        resp = self.client.get('/ce/api/teacher-uploads/?format=json&teacher_id=PLACEHOLDER')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        rows = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        self.assertEqual(rows, [])

    def test_hsadmin_malformed_teacher_id_returns_empty_not_500(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get('/ce/api/teacher-uploads/?format=json&teacher_id=PLACEHOLDER')
        self.assertEqual(resp.status_code, 200)

    def test_instructor_ignores_malformed_teacher_id_and_sees_own(self):
        self.client.force_login(self.instructor_user)
        resp = self.client.get('/ce/api/teacher-uploads/?format=json&teacher_id=PLACEHOLDER')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        rows = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        self.assertEqual({str(r['id']) for r in rows}, {str(self.own_upload.id)})

    def test_ce_valid_teacher_id_still_filters(self):
        self.client.force_login(self.ce_user)
        resp = self.client.get(
            f'/ce/api/teacher-uploads/?format=json&teacher_id={self.teacher.id}')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        rows = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        self.assertEqual({str(r['id']) for r in rows}, {str(self.own_upload.id)})
