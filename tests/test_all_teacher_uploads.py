"""Coverage for the CE Instructors > Files tab endpoint
(`AllTeacherUploadViewSet`, registered as `/ce/api/all-teacher-uploads`).

The viewset subclasses TeacherUploadViewSet so the PT-11 role scoping and the
authorized `download` action are inherited rather than restated. These tests
pin that inheritance — a future refactor that swaps in a hand-rolled CIS-only
queryset has to keep them passing — plus the two presentation properties the
tab depends on: flat columns, and a `media` value that is the download action
rather than a pre-signed S3 URL.
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.teacher import Teacher, TeacherUpload
from cis.views.teacher import AllTeacherUploadViewSet

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class AllTeacherUploadViewSetTests(TestCase):
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

    def setUp(self):
        self.factory = APIRequestFactory()

        self.teacher_a, self.user_a = self._teacher('Adams', 'Ann')
        self.teacher_b, self.user_b = self._teacher('Brown', 'Bob')

        # Assigning a string to a FileField records the name without touching
        # storage, so these fixtures never hit S3.
        self.upload_a = TeacherUpload.objects.create(
            teacher=self.teacher_a,
            media_type='Transcript',
            description='transcript',
            media='teacher_files/a/transcript.pdf',
        )
        self.upload_b = TeacherUpload.objects.create(
            teacher=self.teacher_b,
            media_type='Resume',
            description='resume',
            media='teacher_files/b/resume.pdf',
        )

        self.ce = self._user_in_group('ce')

    def _user_in_group(self, group):
        user = User.objects.create_user(
            username=f'{group}_{_sfx()}', email=f'{group}_{_sfx()}@x.com', password='x')
        user.groups.add(Group.objects.get_or_create(name=group)[0])
        return user

    def _teacher(self, last, first):
        user = self._user_in_group('instructor')
        user.last_name = last
        user.first_name = first
        user.save()
        return Teacher.objects.create(user=user, status='active'), user

    def _list(self, user, **params):
        request = self.factory.get('/ce/api/all-teacher-uploads/', params)
        force_authenticate(request, user=user)
        view = AllTeacherUploadViewSet.as_view({'get': 'list'})
        response = view(request)
        response.render()
        return response

    def _rows(self, response):
        data = response.data
        return data['results'] if isinstance(data, dict) and 'results' in data else data

    # ---- model property ------------------------------------------------

    def test_file_name_is_the_basename(self):
        self.assertEqual(self.upload_a.file_name, 'transcript.pdf')

    # ---- flattening ----------------------------------------------------

    def test_ce_sees_every_upload_with_flat_columns(self):
        rows = self._rows(self._list(self.ce))

        self.assertEqual(len(rows), 2)
        row = next(r for r in rows if r['id'] == str(self.upload_a.id))
        self.assertEqual(row['teacher_last_name'], 'Adams')
        self.assertEqual(row['teacher_first_name'], 'Ann')
        self.assertEqual(row['teacher_email'], self.user_a.email)
        self.assertEqual(row['file_name'], 'transcript.pdf')
        self.assertEqual(row['media_type'], 'Transcript')
        # The flat serializer must not nest the full teacher representation.
        self.assertNotIn('teacher', row)

    def test_default_ordering_is_by_instructor_name(self):
        rows = self._rows(self._list(self.ce))
        self.assertEqual(
            [r['teacher_last_name'] for r in rows], ['Adams', 'Brown'])

    # ---- download link -------------------------------------------------

    def test_media_is_the_authorized_download_action_not_a_signed_url(self):
        rows = self._rows(self._list(self.ce))
        row = next(r for r in rows if r['id'] == str(self.upload_a.id))

        self.assertEqual(
            row['media'], f'/ce/api/teacher-uploads/{self.upload_a.id}/download/')
        # A pre-signed S3 URL would be absolute and carry query auth.
        self.assertFalse(row['media'].startswith('http'))
        self.assertNotIn('X-Amz', row['media'])
        self.assertNotIn('AWSAccessKeyId', row['media'])

    # ---- filtering -----------------------------------------------------

    def test_media_type_filter(self):
        rows = self._rows(self._list(self.ce, media_type='Resume'))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], str(self.upload_b.id))

    # ---- inherited PT-11 scoping ---------------------------------------

    def test_instructor_sees_only_their_own_uploads(self):
        rows = self._rows(self._list(self.user_a))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], str(self.upload_a.id))

    def test_instructor_cannot_widen_scope_with_teacher_id(self):
        rows = self._rows(
            self._list(self.user_a, teacher_id=str(self.teacher_b.id)))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], str(self.upload_a.id))

    def test_unprivileged_role_is_refused(self):
        # The inherited permission_classes (ce | instructor | highschool_admin)
        # reject the request before get_queryset() is consulted.
        response = self._list(self._user_in_group('student'))

        self.assertEqual(response.status_code, 403)

    def test_malformed_teacher_id_is_empty_not_a_500(self):
        response = self._list(self.ce, teacher_id='not-a-uuid')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self._rows(response)), 0)
