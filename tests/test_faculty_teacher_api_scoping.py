"""Enforcement of the faculty -> teacher assignment rule on the teacher APIs.

Spec: docs/superpowers/specs/2026-08-11-faculty-teacher-assignment-design.md
Plan tasks 4 and 5.

`cis.services.faculty_scope.visible_teachers` decides which instructors a
faculty user may see. This module asserts the four teacher-level surfaces the
faculty portal consumes ask it:

  * /ce/api/teacher          (TeacherViewSet)            -- task 4
  * /ce/api/teacher-notes    (TeacherNotesViewSet)       -- task 5
  * /ce/api/teacher-uploads  (TeacherUploadViewSet)      -- task 5
  * /ce/api/class_section    (ClassSectionViewSet)       -- task 5

`ce`, `instructor` and `highschool_admin` behaviour is unchanged everywhere;
the tests that pin that live in test_teacher_viewset_authz.py,
test_teacher_upload_viewset_authz.py and test_class_section_viewset_scoping.py.

EWU has no test factories, so fixtures are built with direct
Model.objects.create(), following test_faculty_scope.py.
"""
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase, RequestFactory
from rest_framework.test import APIClient

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.faculty import FacultyTeacherAssignment
from cis.models.highschool import HighSchool
from cis.models.note import TeacherNote
from cis.models.section import ClassSection
from cis.models.teacher import (
    Teacher, TeacherCourseCertificate, TeacherHighSchool, TeacherUpload,
)
from cis.models.term import AcademicYear, Term

User = get_user_model()


def _suffix():
    return uuid.uuid4().hex[:8]


def _user(group=None):
    sfx = _suffix()
    user = User.objects.create_user(
        username=f'u_{sfx}', email=f'u_{sfx}@example.com', password='x',
        first_name='F', last_name='L',
    )
    if group:
        grp, _ = Group.objects.get_or_create(name=group)
        user.groups.add(grp)
    return user


class FacultyTeacherScopingFixture:
    """One faculty member overseeing two courses.

    `assigned_course` has a FacultyTeacherAssignment for `mine` only, so
    `theirs` -- certified for the same course -- must disappear from every
    faculty-facing surface. `open_course` has no assignment rows, so its
    certified teacher `fallback` stays visible (the ship-dark guarantee).
    `stranger` is certified for a course this faculty does not oversee at all.
    """

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
        for name in ('ce', 'faculty', 'instructor', 'highschool_admin'):
            Group.objects.get_or_create(name=name)

        self.year = AcademicYear.objects.create(name=f'AY-{_suffix()}')
        self.term = Term.objects.create(
            academic_year=self.year, code='FA', label=f'Fall-{_suffix()}')
        self.cohort = Cohort.objects.create(
            name=f'Co-{_suffix()}', designator='CO')
        self.hs = HighSchool.objects.create(name=f'HS-{_suffix()}')

        # The ce branch of TeacherViewSet runs through the campus gate, which
        # drops every teacher certified for a course outside the ce user's
        # process_campus list. Give the courses a prefixed campus and the ce
        # user permission to process it, so the ce assertions below are about
        # this change and not about the campus gate.
        from cis.models.course import Campus
        from django.conf import settings as dj_settings
        self.campus = Campus.objects.create(
            name=f'Campus-{_suffix()}',
            code=f'{dj_settings.CAMPUS_CODE_PREFIX}{_suffix()}')

        self.faculty_user = _user('faculty')
        self.other_faculty_user = _user('faculty')
        self.ce_user = _user('ce')
        self.ce_user.campus = {'process_campus': [str(self.campus.id)]}
        self.ce_user.save()

        self.assigned_course = self._course('Assigned')
        self.open_course = self._course('Open')
        self.foreign_course = self._course('Foreign')
        self._oversees(self.assigned_course)
        self._oversees(self.open_course)
        self._oversees(self.foreign_course, user=self.other_faculty_user)

        self.mine = self._teacher()
        self.theirs = self._teacher()
        self.fallback = self._teacher()
        self.stranger = self._teacher()
        self._certifies(self.mine, self.assigned_course)
        self._certifies(self.theirs, self.assigned_course)
        self._certifies(self.fallback, self.open_course)
        self._certifies(self.stranger, self.foreign_course)

        FacultyTeacherAssignment.objects.create(
            user=self.faculty_user, course=self.assigned_course,
            teacher=self.mine, academic_year=self.year)

        # visible_teachers() defaults its year to active_academic_year(),
        # which is None in a fresh test database -- every assignment row would
        # then look like "some other year" and nothing would ever narrow.
        patcher = mock.patch(
            'cis.services.faculty_scope.active_academic_year',
            return_value=self.year)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    def _course(self, title):
        return Course.objects.create(
            catalog_number=f'1{_suffix()}', title=f'{title}-{_suffix()}',
            cohort=self.cohort, campus=self.campus)

    def _teacher(self):
        return Teacher.objects.create(user=_user('instructor'), status='active')

    def _oversees(self, course, user=None):
        return CourseAdministrator.objects.create(
            course=course, user=user or self.faculty_user, status='Active')

    def _certifies(self, teacher, course):
        ths, _ = TeacherHighSchool.objects.get_or_create(
            teacher=teacher, highschool=self.hs)
        return TeacherCourseCertificate.objects.create(
            teacher_highschool=ths, course=course)

    @staticmethod
    def _ids(resp):
        payload = resp.json()
        rows = (payload['results']
                if isinstance(payload, dict) and 'results' in payload
                else payload)
        return {str(r['id']) for r in rows}


class TeacherViewSetFacultyScopingTests(FacultyTeacherScopingFixture, TestCase):
    """Task 4 -- /ce/api/teacher."""

    def test_faculty_sees_only_their_visible_teachers(self):
        self.client.force_login(self.faculty_user)
        resp = self.client.get('/ce/api/teacher/?format=json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self._ids(resp), {str(self.mine.id), str(self.fallback.id)})

    def test_faculty_cannot_retrieve_a_teacher_outside_the_visible_set(self):
        self.client.force_login(self.faculty_user)
        resp = self.client.get(f'/ce/api/teacher/{self.theirs.id}/?format=json')
        self.assertEqual(resp.status_code, 404)

    def test_faculty_can_retrieve_a_teacher_inside_the_visible_set(self):
        self.client.force_login(self.faculty_user)
        resp = self.client.get(f'/ce/api/teacher/{self.mine.id}/?format=json')
        self.assertEqual(resp.status_code, 200)

    def test_ce_still_sees_every_teacher(self):
        self.client.force_login(self.ce_user)
        resp = self.client.get('/ce/api/teacher/?format=json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self._ids(resp),
            {str(self.mine.id), str(self.theirs.id),
             str(self.fallback.id), str(self.stranger.id)},
        )

    def test_another_facultys_coordinator_id_cannot_widen_the_result(self):
        """faculty_coordinator_id filters by that faculty's courses; the new
        scoping is an additional AND, never a replacement. Passing the other
        faculty's id must not surface the other faculty's instructors."""
        self.client.force_login(self.faculty_user)
        resp = self.client.get(
            '/ce/api/teacher/?format=json'
            f'&faculty_coordinator_id={self.other_faculty_user.id}')
        self.assertEqual(resp.status_code, 200)
        ids = self._ids(resp)
        self.assertNotIn(str(self.stranger.id), ids)
        self.assertNotIn(str(self.theirs.id), ids)

    def test_own_coordinator_id_still_narrows_to_that_facultys_courses(self):
        self.client.force_login(self.faculty_user)
        resp = self.client.get(
            '/ce/api/teacher/?format=json'
            f'&faculty_coordinator_id={self.faculty_user.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self._ids(resp), {str(self.mine.id), str(self.fallback.id)})


class TeacherNotesFacultyScopingTests(FacultyTeacherScopingFixture, TestCase):
    """Task 5 -- /ce/api/teacher-notes.

    The endpoint's permission_classes are CIS_user_only, so a faculty user is
    403 today and this change does not widen that. The scoping is asserted at
    the queryset level (the same RequestFactory idiom as
    test_class_section_viewset_scoping.py), which is what protects the data the
    day the faculty portal is granted the endpoint.
    """

    def setUp(self):
        super().setUp()
        self.note_mine = TeacherNote.objects.create(
            teacher=self.mine, note='visible', createdby=self.ce_user,
            meta={'type': 'private'})
        self.note_theirs = TeacherNote.objects.create(
            teacher=self.theirs, note='hidden', createdby=self.ce_user,
            meta={'type': 'private'})

    def _qs(self, user, **params):
        from cis.views.teacher import TeacherNotesViewSet
        vs = TeacherNotesViewSet()
        req = RequestFactory().get('/', params)
        req.user = user
        vs.request = req
        return vs.get_queryset()

    def test_faculty_queryset_excludes_notes_for_out_of_scope_teachers(self):
        ids = {r.id for r in self._qs(self.faculty_user)}
        self.assertIn(self.note_mine.id, ids)
        self.assertNotIn(self.note_theirs.id, ids)

    def test_faculty_teacher_id_for_an_out_of_scope_teacher_returns_nothing(self):
        ids = {r.id for r in self._qs(
            self.faculty_user, teacher_id=str(self.theirs.id))}
        self.assertEqual(ids, set())

    def test_ce_queryset_is_unchanged(self):
        ids = {r.id for r in self._qs(self.ce_user)}
        self.assertEqual(ids, {self.note_mine.id, self.note_theirs.id})

    def test_faculty_role_is_still_forbidden_over_http(self):
        """Documents that this change scopes, and does not widen, access."""
        self.client.force_login(self.faculty_user)
        resp = self.client.get('/ce/api/teacher-notes/?format=json')
        self.assertEqual(resp.status_code, 403)


class TeacherUploadFacultyScopingTests(FacultyTeacherScopingFixture, TestCase):
    """Task 5 -- /ce/api/teacher-uploads. Same reachability note as notes."""

    def setUp(self):
        super().setUp()
        # No media file: TeacherUpload.media is a private-S3 FileField and
        # attaching one here would need a live bucket (which is exactly what
        # breaks test_teacher_upload_viewset_authz in this environment). These
        # tests only assert which rows the queryset returns.
        self.upload_mine = TeacherUpload.objects.create(
            teacher=self.mine, media_type='Resume')
        self.upload_theirs = TeacherUpload.objects.create(
            teacher=self.theirs, media_type='Resume')

    def _qs(self, user, **params):
        from cis.views.teacher import TeacherUploadViewSet
        vs = TeacherUploadViewSet()
        req = RequestFactory().get('/', params)
        req.user = user
        vs.request = req
        return vs.get_queryset()

    def test_faculty_queryset_excludes_out_of_scope_uploads(self):
        ids = {r.id for r in self._qs(self.faculty_user)}
        self.assertIn(self.upload_mine.id, ids)
        self.assertNotIn(self.upload_theirs.id, ids)

    def test_faculty_teacher_id_for_an_out_of_scope_teacher_returns_nothing(self):
        ids = {r.id for r in self._qs(
            self.faculty_user, teacher_id=str(self.theirs.id))}
        self.assertEqual(ids, set())

    def test_faculty_malformed_teacher_id_is_empty_not_an_error(self):
        self.assertEqual(
            list(self._qs(self.faculty_user, teacher_id='PLACEHOLDER')), [])

    def test_ce_queryset_is_unchanged(self):
        ids = {r.id for r in self._qs(self.ce_user)}
        self.assertEqual(ids, {self.upload_mine.id, self.upload_theirs.id})

    def test_faculty_role_is_still_forbidden_over_http(self):
        self.client.force_login(self.faculty_user)
        resp = self.client.get('/ce/api/teacher-uploads/?format=json')
        self.assertEqual(resp.status_code, 403)


class ClassSectionFacultyTeacherScopingTests(
        FacultyTeacherScopingFixture, TestCase):
    """Task 5 -- /ce/api/class_section?teacher_id=...

    This endpoint is reachable by any authenticated user (no permission_classes;
    PT-25 scopes it in the queryset), and the faculty teacher-detail page calls
    it with a teacher_id. A teacher_id outside the faculty's visible set must
    yield nothing.

    Only the teacher_id path is scoped: the same endpoint backs the faculty
    portal's Class Sections / Offered Classes pages, which pass no teacher_id,
    and narrowing those would change what faculty see before any assignment row
    exists -- which the spec's rollout section forbids.
    """

    def setUp(self):
        super().setUp()
        self.section_mine = ClassSection.objects.create(
            term=self.term, course=self.assigned_course, teacher=self.mine)
        self.section_theirs = ClassSection.objects.create(
            term=self.term, course=self.assigned_course, teacher=self.theirs)

    def _qs(self, user, **params):
        from cis.views.section import ClassSectionViewSet
        vs = ClassSectionViewSet()
        req = RequestFactory().get('/', params)
        req.user = user
        vs.request = req
        return vs.get_queryset()

    def test_faculty_may_list_sections_for_a_visible_teacher(self):
        ids = {r.id for r in self._qs(
            self.faculty_user, term='-1', teacher_id=str(self.mine.id))}
        self.assertEqual(ids, {self.section_mine.id})

    def test_faculty_gets_nothing_for_a_teacher_outside_the_visible_set(self):
        ids = {r.id for r in self._qs(
            self.faculty_user, term='-1', teacher_id=str(self.theirs.id))}
        self.assertEqual(ids, set())

    def test_faculty_malformed_teacher_id_is_empty_not_an_error(self):
        self.assertEqual(
            list(self._qs(self.faculty_user, term='-1',
                          teacher_id='PLACEHOLDER')),
            [])

    def test_faculty_listing_without_a_teacher_id_is_unchanged(self):
        ids = {r.id for r in self._qs(self.faculty_user, term='-1')}
        self.assertEqual(ids, {self.section_mine.id, self.section_theirs.id})

    def test_ce_may_still_list_sections_for_any_teacher(self):
        ids = {r.id for r in self._qs(
            self.ce_user, term='-1', teacher_id=str(self.theirs.id))}
        self.assertEqual(ids, {self.section_theirs.id})
