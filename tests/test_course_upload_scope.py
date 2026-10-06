"""package-cis#60: course uploads are scoped by role.

  * /ce/api/course-uploads/ (CourseUploadViewSet) is open to CE, faculty and
    instructors, and used to return any course's uploads for any `course_id`
    -- or every upload when `course_id` was dropped. CE keeps everything;
    faculty see the courses they actively administer, instructors the courses
    they are certified for.
  * delete_course_upload (/ce/add_new_ajax/) was CE-only, so the faculty
    Syllabi Templates modal could upload but not delete. It now admits faculty,
    looking the upload up through the courses they administer (404 otherwise).
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIRequestFactory

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import Cohort, Course, CourseAdministrator, CourseUpload
from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher, TeacherCourseCertificate, TeacherHighSchool

User = get_user_model()


def _user_in(*groups):
    sfx = uuid.uuid4().hex[:8]
    user = User.objects.create_user(
        username=f'u_{sfx}', email=f'u_{sfx}@example.com', password='x',
        first_name='F', last_name='L',
    )
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    return user


class _Fixture(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login handler blows up in tests (request
        # has no usable IP). Disconnect for the duration of the case.
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
        cohort = Cohort.objects.create(name='Upl Co', designator='UPL')
        cls.course_a = Course.objects.create(
            name='UplA', title='A', catalog_number='601', credit_hours=3,
            cohort=cohort)
        cls.course_b = Course.objects.create(
            name='UplB', title='B', catalog_number='602', credit_hours=3,
            cohort=cohort)

        cls.upload_a = CourseUpload.objects.create(
            course=cls.course_a, media_type='Syllabus Template')
        cls.upload_b = CourseUpload.objects.create(
            course=cls.course_b, media_type='Syllabus Template')

        cls.ce = _user_in('ce')

        # Faculty A administers course A; the colleague administers course B.
        cls.faculty_a = _user_in('faculty')
        CourseAdministrator.objects.create(
            course=cls.course_a, user=cls.faculty_a, role='Faculty',
            status='Active')
        colleague = _user_in('faculty')
        CourseAdministrator.objects.create(
            course=cls.course_b, user=colleague, role='Faculty',
            status='Active')

        # Faculty whose only row on course B is inactive.
        cls.faculty_inactive = _user_in('faculty')
        CourseAdministrator.objects.create(
            course=cls.course_b, user=cls.faculty_inactive, role='Faculty',
            status='Inactive')

        # Instructor certified for course A only.
        cls.instructor = _user_in('instructor')
        teacher = Teacher.objects.create(user=cls.instructor)
        ths = TeacherHighSchool.objects.create(
            teacher=teacher, highschool=HighSchool.objects.create(name='Upl HS'),
            status='active')
        TeacherCourseCertificate.objects.create(
            teacher_highschool=ths, course=cls.course_a, status='Teaching')
        TeacherCourseCertificate.objects.create(
            teacher_highschool=ths, course=cls.course_b, status='Inactive')

        cls.student = _user_in('student')


class CourseUploadFeedScopeTests(_Fixture):

    def _ids(self, user, **params):
        from cis.views.course import CourseUploadViewSet

        request = APIRequestFactory().get('/ce/api/course-uploads/', params)
        request.user = user
        view = CourseUploadViewSet()
        view.request = request
        view.format_kwarg = None
        return set(view.get_queryset().values_list('id', flat=True))

    def test_ce_sees_every_upload(self):
        self.assertEqual(
            self._ids(self.ce), {self.upload_a.id, self.upload_b.id})
        self.assertEqual(
            self._ids(self.ce, course_id=str(self.course_b.id)),
            {self.upload_b.id})

    def test_faculty_without_course_id_sees_only_their_courses(self):
        self.assertEqual(self._ids(self.faculty_a), {self.upload_a.id})

    def test_faculty_with_own_course_id(self):
        self.assertEqual(
            self._ids(self.faculty_a, course_id=str(self.course_a.id)),
            {self.upload_a.id})

    def test_faculty_with_colleagues_course_id_sees_nothing(self):
        self.assertEqual(
            self._ids(self.faculty_a, course_id=str(self.course_b.id)), set())

    def test_inactive_course_administrator_row_grants_nothing(self):
        self.assertEqual(self._ids(self.faculty_inactive), set())

    def test_instructor_sees_only_certified_courses(self):
        # The Inactive certificate on course B does not count.
        self.assertEqual(self._ids(self.instructor), {self.upload_a.id})
        self.assertEqual(
            self._ids(self.instructor, course_id=str(self.course_b.id)), set())

    def test_non_uuid_course_id_returns_nothing(self):
        self.assertEqual(self._ids(self.ce, course_id='not-a-uuid'), set())
        self.assertEqual(
            self._ids(self.faculty_a, course_id='not-a-uuid'), set())

    def test_student_is_refused_by_the_endpoint(self):
        from rest_framework.test import APIClient

        client = APIClient(REMOTE_ADDR='127.0.0.1')
        client.force_login(self.student)
        response = client.get('/ce/api/course-uploads/?format=json')
        self.assertEqual(response.status_code, 403)


class DeleteCourseUploadScopeTests(_Fixture):

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.url = reverse('cis:add_new_ajax')

    def _delete(self, user, upload_id):
        self.client.force_login(user)
        return self.client.get(self.url, {
            'model': 'delete_course_upload', 'upload_id': str(upload_id),
        })

    def test_faculty_deletes_upload_on_their_course(self):
        response = self._delete(self.faculty_a, self.upload_a.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('status'), 'success')
        self.assertFalse(
            CourseUpload.objects.filter(pk=self.upload_a.pk).exists())

    def test_faculty_gets_404_on_a_colleagues_course(self):
        response = self._delete(self.faculty_a, self.upload_b.pk)

        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            CourseUpload.objects.filter(pk=self.upload_b.pk).exists())

    def test_inactive_course_administrator_gets_404(self):
        response = self._delete(self.faculty_inactive, self.upload_b.pk)

        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            CourseUpload.objects.filter(pk=self.upload_b.pk).exists())

    def test_instructor_is_refused(self):
        # Certified for course A, but deleting is CE/faculty only.
        response = self._delete(self.instructor, self.upload_a.pk)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            CourseUpload.objects.filter(pk=self.upload_a.pk).exists())

    def test_student_is_refused(self):
        response = self._delete(self.student, self.upload_a.pk)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            CourseUpload.objects.filter(pk=self.upload_a.pk).exists())

    def test_ce_deletes_any_upload(self):
        response = self._delete(self.ce, self.upload_b.pk)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            CourseUpload.objects.filter(pk=self.upload_b.pk).exists())

    def test_non_uuid_upload_id_is_404_not_500(self):
        for user in (self.ce, self.faculty_a):
            with self.subTest(user=user.username):
                response = self._delete(user, 'not-a-uuid')
                self.assertEqual(response.status_code, 404)
