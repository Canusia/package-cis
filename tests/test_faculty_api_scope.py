"""Faculty scoping on the /ce/api/* viewsets (package-cis#114 item 8).

`user_has_faculty_role` admits faculty to several CE viewsets that returned
rows outside the courses and instructors they oversee. Every one now runs
the same order: CE first (unchanged -- `user_has_faculty_role` is also True
for CE, so CE must be tested first), then faculty narrowed through
`cis.services.faculty_scope`, otherwise nothing.

For each endpoint:
  * a faculty member sees only rows in their scope;
  * a faculty member with no courses gets nothing;
  * retrieving an out-of-scope id is a 404;
  * CE is unchanged.

ClassSectionViewSet narrows only once the mentor is set up for the active
academic year (rollout gate, see `faculty_scope.section_scope_applies`).
"""
import datetime
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from rest_framework.test import APIClient

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.faculty import FacultyCoordinator, FacultyYearSetup
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator, HSPosition, HSAdministratorPosition,
)
from cis.models.section import ClassSection, StudentDropRequest, StudentRegistration
from cis.models.student import ParentConsent, Student
from cis.models.teacher import Teacher, TeacherCourseCertificate, TeacherHighSchool
from cis.models.teacher_applicant import (
    ApplicantCourseReviewer, ApplicantSchoolCourse, TeacherApplication,
)
from cis.models.term import AcademicYear, Term

User = get_user_model()


class FacultyApiScopeTests(TestCase):
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
    def _user(cls, name, *groups):
        user = User.objects.create_user(
            username=name, email=f'{name}@example.com', password='x',
            first_name=name.title(), last_name='Test')
        for g in groups:
            user.groups.add(Group.objects.get(name=g))
        return user

    @classmethod
    def setUpTestData(cls):
        for name in ('ce', 'faculty', 'instructor', 'highschool_admin', 'student'):
            Group.objects.get_or_create(name=name)
        # Registration signals attribute notes to 'cron' without a request.
        User.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})

        cls.year = AcademicYear.objects.create(name='2025-2026')
        cls.term = Term.objects.create(
            academic_year=cls.year, code='202610', label='Fall 2025')
        cohort = Cohort.objects.create(designator='ENG')
        cls.mine = Course.objects.create(
            catalog_number='101', title='English Composition', name='ENGL101',
            cohort=cohort)
        cls.other = Course.objects.create(
            catalog_number='201', title='Organic Chemistry', name='CHEM201',
            cohort=cohort)

        cls.hs_a = HighSchool.objects.create(name='HS Alpha')
        cls.hs_b = HighSchool.objects.create(name='HS Beta')

        # One instructor certified for both courses; sections in each.
        cls.instructor_user = cls._user('inst', 'instructor')
        cls.teacher = Teacher.objects.create(user=cls.instructor_user)
        ths = TeacherHighSchool.objects.create(
            teacher=cls.teacher, highschool=cls.hs_a, status='In the Program')
        cls.cert_mine = TeacherCourseCertificate.objects.create(
            teacher_highschool=ths, course=cls.mine)
        cls.cert_other = TeacherCourseCertificate.objects.create(
            teacher_highschool=ths, course=cls.other)
        cls.other_teacher = Teacher.objects.create(user=cls._user('inst2'))
        TeacherHighSchool.objects.create(
            teacher=cls.other_teacher, highschool=cls.hs_b, status='In the Program')

        cls.sec_mine = ClassSection.objects.create(
            class_number='1001', section_number='01', term=cls.term,
            course=cls.mine, teacher=cls.teacher)
        cls.sec_other = ClassSection.objects.create(
            class_number='2002', section_number='02', term=cls.term,
            course=cls.other, teacher=cls.other_teacher)

        cls.stu_mine, cls.reg_mine = cls._registration(cls.sec_mine, 'aaa', cls.hs_a)
        cls.stu_other, cls.reg_other = cls._registration(cls.sec_other, 'bbb', cls.hs_b)

        cls.pc_mine = ParentConsent.objects.create(
            student=cls.stu_mine, term=cls.term, parent_signature='x')
        cls.pc_other = ParentConsent.objects.create(
            student=cls.stu_other, term=cls.term, parent_signature='x')

        cls.drop_mine = StudentDropRequest.objects.create(
            student=cls.stu_mine, registration=cls.reg_mine)
        cls.drop_other = StudentDropRequest.objects.create(
            student=cls.stu_other, registration=cls.reg_other)

        # Faculty: oversees `mine`; a colleague co-administers `mine` and
        # alone administers `other`; a third administers nothing.
        cls.faculty_user = cls._user('fac', 'faculty')
        cls.coordinator = FacultyCoordinator.objects.create(user=cls.faculty_user)
        cls.ca_mine = CourseAdministrator.objects.create(
            course=cls.mine, user=cls.faculty_user, role='Faculty', status='Active')
        cls.colleague = cls._user('colleague', 'faculty')
        FacultyCoordinator.objects.create(user=cls.colleague)
        cls.ca_colleague_mine = CourseAdministrator.objects.create(
            course=cls.mine, user=cls.colleague, role='Faculty', status='Active')
        cls.ca_colleague_other = CourseAdministrator.objects.create(
            course=cls.other, user=cls.colleague, role='Faculty', status='Active')
        cls.idle_faculty = cls._user('idle', 'faculty')
        FacultyCoordinator.objects.create(user=cls.idle_faculty)

        # Superuser so CE's own campus gate (unchanged here) does not hide the
        # campus-less fixtures.
        cls.ce_user = cls._user('ce', 'ce')
        cls.ce_user.is_superuser = True
        cls.ce_user.save()

        hsa_user = cls._user('hsadmin', 'highschool_admin')
        cls.hsadmin_user = hsa_user
        HSAdministratorPosition.objects.create(
            hsadmin=HSAdministrator.objects.create(user=hsa_user),
            highschool=cls.hs_a, position=HSPosition.objects.create(name='Principal'),
            status='Active')

        # Teacher applications: one per course, the colleague reviews both.
        cls.app_mine = cls._application('appa', cls.mine)
        cls.app_other = cls._application('appb', cls.other)
        cls.rev_mine = ApplicantCourseReviewer.objects.create(
            application_course=cls.app_mine.applicantschoolcourse_set.get(),
            reviewer=cls.colleague)
        cls.rev_other = ApplicantCourseReviewer.objects.create(
            application_course=cls.app_other.applicantschoolcourse_set.get(),
            reviewer=cls.colleague)

    @classmethod
    def _registration(cls, section, tag, highschool):
        user = cls._user(f'stu_{tag}', 'student')
        student = Student.objects.create(user=user, highschool=highschool)
        reg = StudentRegistration.objects.create(
            student=student, class_section=section, status='registered',
            status_changed_on={})
        return student, reg

    @classmethod
    def _application(cls, tag, course):
        app = TeacherApplication.objects.create(
            user=cls._user(tag), createdon=datetime.date.today(),
            status_changed_on={})
        ApplicantSchoolCourse.objects.create(
            teacherapplication=app, course=course, misc_info={})
        return app

    # -- helpers -------------------------------------------------------------

    def _get(self, user, url, params=None):
        client = APIClient(REMOTE_ADDR='127.0.0.1')
        client.force_login(user)
        params = dict(params or {})
        params.setdefault('format', 'json')
        return client.get(url, params)

    def _ids(self, user, url, params=None):
        resp = self._get(user, url, params)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        payload = resp.json()
        rows = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        return {str(r['id']) for r in rows}

    def _assert_scoped(self, url, mine, other, params=None):
        """Faculty: only `mine`; idle faculty: nothing; CE: both; retrieve 404."""
        self.assertEqual(self._ids(self.faculty_user, url, params), {str(mine.id)})
        self.assertEqual(self._ids(self.idle_faculty, url, params), set())
        self.assertTrue(
            {str(mine.id), str(other.id)} <= self._ids(self.ce_user, url, params))
        detail = self._get(self.faculty_user, f'{url}{other.id}/', params)
        self.assertEqual(detail.status_code, 404)
        detail = self._get(self.faculty_user, f'{url}{mine.id}/', params)
        self.assertEqual(detail.status_code, 200)

    # -- registrations, consents, drops, students -----------------------------

    def test_registration(self):
        self._assert_scoped('/ce/api/registration/', self.reg_mine, self.reg_other,
                            {'term': '-3'})

    def test_registration_student_param_cannot_widen(self):
        ids = self._ids(self.faculty_user, '/ce/api/registration/',
                        {'term': '-3', 'student': str(self.stu_other.id)})
        self.assertEqual(ids, set())

    def test_registration_instructor_unchanged(self):
        ids = self._ids(self.instructor_user, '/ce/api/registration/', {'term': '-3'})
        self.assertEqual(ids, {str(self.reg_mine.id)})

    def test_parent_consent(self):
        self._assert_scoped('/ce/api/parent_consent/', self.pc_mine, self.pc_other)

    def test_parent_consent_instructor_sees_own_students_only(self):
        ids = self._ids(self.instructor_user, '/ce/api/parent_consent/')
        self.assertEqual(ids, {str(self.pc_mine.id)})

    def test_student_drop(self):
        self._assert_scoped('/ce/api/drop_wd_req/', self.drop_mine, self.drop_other,
                            {'term': ''})

    def test_student_drop_hsadmin_sees_own_schools_only(self):
        ids = self._ids(self.hsadmin_user, '/ce/api/drop_wd_req/', {'term': ''})
        self.assertEqual(ids, {str(self.drop_mine.id)})

    def test_student(self):
        self._assert_scoped('/ce/api/student/', self.stu_mine, self.stu_other)

    # -- class sections --------------------------------------------------------

    def _active_year(self, year):
        patcher = mock.patch(
            'cis.services.faculty_scope.active_academic_year', return_value=year)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_class_section_narrowed_once_year_is_set_up(self):
        self._active_year(self.year)
        for user in (self.faculty_user, self.idle_faculty):
            FacultyYearSetup.objects.create(user=user, academic_year=self.year)
        self._assert_scoped('/ce/api/class_section/', self.sec_mine,
                            self.sec_other, {'term': '-1'})

    def test_class_section_unchanged_before_year_is_set_up(self):
        # Rollout gate: no FacultyYearSetup for the active year -> the feed
        # keeps its old behaviour for faculty.
        self._active_year(self.year)
        ids = self._ids(self.faculty_user, '/ce/api/class_section/', {'term': '-1'})
        self.assertTrue({str(self.sec_mine.id), str(self.sec_other.id)} <= ids)

    def test_class_section_course_administrator_param_is_own_id_only(self):
        self._active_year(self.year)
        ids = self._ids(self.faculty_user, '/ce/api/class_section/', {
            'term': '-1', 'course_administrator_user_id': str(self.colleague.id)})
        self.assertEqual(ids, set())
        ids = self._ids(self.faculty_user, '/ce/api/class_section/', {
            'term': '-1', 'course_administrator_user_id': str(self.faculty_user.id)})
        self.assertEqual(ids, {str(self.sec_mine.id)})

    def test_class_section_ce_course_administrator_param_unchanged(self):
        ids = self._ids(self.ce_user, '/ce/api/class_section/', {
            'term': '-1', 'course_administrator_user_id': str(self.colleague.id)})
        self.assertEqual(ids, {str(self.sec_mine.id), str(self.sec_other.id)})

    def test_class_section_instructor_unchanged(self):
        self._active_year(self.year)
        ids = self._ids(self.instructor_user, '/ce/api/class_section/', {'term': '-1'})
        self.assertEqual(ids, {str(self.sec_mine.id)})

    # -- courses, course administrators, applications -------------------------

    def test_course(self):
        self._assert_scoped('/ce/api/course/', self.mine, self.other)

    def test_course_still_forbidden_for_instructors(self):
        resp = self._get(self.instructor_user, '/ce/api/course/')
        self.assertEqual(resp.status_code, 403)

    def test_course_administrator(self):
        ids = self._ids(self.faculty_user, '/ce/api/course_administrator/')
        self.assertEqual(ids, {str(self.ca_mine.id), str(self.ca_colleague_mine.id)})
        self.assertEqual(self._ids(self.idle_faculty, '/ce/api/course_administrator/'), set())
        self.assertTrue({str(self.ca_mine.id), str(self.ca_colleague_other.id)}
                        <= self._ids(self.ce_user, '/ce/api/course_administrator/'))
        resp = self._get(self.faculty_user,
                         f'/ce/api/course_administrator/{self.ca_colleague_other.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_course_administrator_ignores_other_users_id(self):
        ids = self._ids(self.faculty_user, '/ce/api/course_administrator/', {
            'faculty_coordinator_user_id': str(self.colleague.id)})
        self.assertEqual(ids, {str(self.ca_mine.id)})
        ids = self._ids(self.faculty_user, '/ce/api/course_administrator/', {
            'course_id': str(self.other.id)})
        self.assertEqual(ids, set())

    def test_teacher_application(self):
        self._assert_scoped('/ce/api/teacher_application/', self.app_mine, self.app_other)

    def test_teacher_application_reviewer(self):
        self._assert_scoped('/ce/api/teacher_application_reviewers/',
                            self.rev_mine, self.rev_other)

    def test_teacher_application_ignores_other_reviewer_id(self):
        ids = self._ids(self.faculty_user, '/ce/api/teacher_application/', {
            'reviewer': str(self.colleague.id)})
        self.assertEqual(ids, set())
        ids = self._ids(self.faculty_user, '/ce/api/teacher_application/', {
            'course': str(self.other.id)})
        self.assertEqual(ids, set())

    def test_teacher_application_assigned_reviewer_sees_own_assignments(self):
        # The colleague reviews both applications and administers both courses;
        # a reviewer assignment alone also counts.
        CourseAdministrator.objects.filter(user=self.colleague).delete()
        ids = self._ids(self.colleague, '/ce/api/teacher_application/')
        self.assertEqual(ids, {str(self.app_mine.id), str(self.app_other.id)})

    # -- teacher serializer columns -------------------------------------------

    def test_teacher_active_courses_limited_to_visible_pairs(self):
        resp = self._get(self.faculty_user, f'/ce/api/teacher/{self.teacher.id}/')
        self.assertEqual(resp.status_code, 200)
        courses = {c['course']['id'] for c in resp.json()['active_courses']}
        self.assertEqual(courses, {str(self.mine.id)})
        self.assertEqual(resp.json()['active_highschools'], ['HS Alpha'])

    def test_teacher_active_courses_unchanged_for_ce(self):
        resp = self._get(self.ce_user, f'/ce/api/teacher/{self.teacher.id}/')
        self.assertEqual(resp.status_code, 200)
        courses = {c['course']['id'] for c in resp.json()['active_courses']}
        self.assertEqual(courses, {str(self.mine.id), str(self.other.id)})
