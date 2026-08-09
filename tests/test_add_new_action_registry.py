"""
Authorization tests for the /ce/add_new_ajax/ action registry.

Before this registry, eleven of these slugs had no authorization check at any
layer — not on the URL (/ce/add_new_ajax/ carries no role guard), not in the
dispatch branch, and not in the handler. Both /ce/add_new_ajax/ and
/highschool_admin/ajax/ reach the same code, and LoginRequiredMiddleware means
the floor is any authenticated user.

The suite that would have caught that is one 403 assertion per slug.
"""
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from cis.models.customuser import CustomUser
from cis.actions.registry import add_new_actions

ROLES = [
    'applicant', 'ce', 'district_admin', 'faculty',
    'highschool_admin', 'instructor', 'student', 'speaker',
]

# Every non-notes slug the registry owns, and who may call it.
CIS_ONLY_SLUGS = [
    'district',
    'districtadministratorrole',
    'highschoolcollegeadvisor',
    'teacherhighschool',
    'teachercoursecertificate',
    'delete_teacher_upload',
    'course_administrator',
    'delete_course_upload',
    'faculty_course_administrator',
    'facultycoursecoordinator',
    'classsection',
    'courseoffering',
    'student',
    'studentcampusid',
    'studentregistration',
    'eventspeaker',
    'eventcohort',
    'applicationcoursereviewer',
    'supportrequest',
]

HS_ADMIN_SLUGS = ['hsadministratorrole']


def make_user(email, roles=()):
    for name in ROLES:
        Group.objects.get_or_create(name=name)
    user = CustomUser.objects.create(
        username=email, email=email, first_name='Test', last_name='User',
    )
    for role in roles:
        user.groups.add(Group.objects.get(name=role))
    return user


class RegistryCoverageTests(TestCase):

    def test_every_non_notes_slug_is_registered(self):
        registered = set()
        for group in add_new_actions._groups.values():
            registered.update(group['actions'].keys())

        for slug in CIS_ONLY_SLUGS + HS_ADMIN_SLUGS:
            with self.subTest(slug=slug):
                self.assertIn(slug, registered)

    def test_every_action_declares_a_permission(self):
        for group in add_new_actions._groups.values():
            for slug, action in group['actions'].items():
                with self.subTest(slug=slug):
                    self.assertIsNotNone(action.get('permission'))

    def test_registering_without_a_permission_raises(self):
        from cis.actions.registry import GuardedActionRegistry

        registry = GuardedActionRegistry()

        with self.assertRaises(ValueError):
            @registry.action('g', label='Ungated', scope=['detail'], slug='ungated')
            def _ungated(request):
                return None


class PermissionEnforcementTests(TestCase):
    """A non-privileged role is refused before any handler runs."""

    def setUp(self):
        self.factory = RequestFactory()

    def _dispatch(self, slug, user, method='post'):
        request = getattr(self.factory, method)('/ce/add_new_ajax/', {'model': slug})
        request.user = user
        return add_new_actions.dispatch(request, slug)

    def test_student_is_refused_every_cis_only_slug(self):
        user = make_user('student@example.com', roles=['student'])
        for slug in CIS_ONLY_SLUGS:
            with self.subTest(slug=slug):
                self.assertEqual(self._dispatch(slug, user).status_code, 403)

    def test_hs_admin_is_refused_every_cis_only_slug(self):
        user = make_user('hsadmin@example.com', roles=['highschool_admin'])
        for slug in CIS_ONLY_SLUGS:
            with self.subTest(slug=slug):
                self.assertEqual(self._dispatch(slug, user).status_code, 403)

    def test_instructor_is_refused_every_cis_only_slug(self):
        user = make_user('instructor@example.com', roles=['instructor'])
        for slug in CIS_ONLY_SLUGS:
            with self.subTest(slug=slug):
                self.assertEqual(self._dispatch(slug, user).status_code, 403)

    def test_roleless_user_is_refused(self):
        user = make_user('noroles@example.com', roles=[])
        for slug in CIS_ONLY_SLUGS + HS_ADMIN_SLUGS:
            with self.subTest(slug=slug):
                self.assertEqual(self._dispatch(slug, user).status_code, 403)

    def test_unknown_slug_is_rejected(self):
        user = make_user('ce@example.com', roles=['ce'])
        response = self._dispatch('no_such_model', user)
        self.assertEqual(response.status_code, 400)


class UploadDeletionTests(TestCase):
    """
    delete_teacher_upload / delete_course_upload took an id from the query
    string and deleted the row, with add_new_ajax as their only entry point.
    """

    def setUp(self):
        self.factory = RequestFactory()

    def _delete(self, slug, user, upload_id):
        request = self.factory.get(
            '/ce/add_new_ajax/', {'model': slug, 'upload_id': str(upload_id)}
        )
        request.user = user
        return add_new_actions.dispatch(request, slug)

    def _teacher_upload(self):
        from cis.models.teacher import Teacher, TeacherUpload

        user = make_user('teacher-owner@example.com', roles=['instructor'])
        teacher = Teacher.objects.create(user=user)
        return TeacherUpload.objects.create(
            teacher=teacher, media_type='Transcript',
        )

    def test_student_cannot_delete_a_teacher_upload(self):
        from cis.models.teacher import TeacherUpload

        upload = self._teacher_upload()
        attacker = make_user('attacker@example.com', roles=['student'])

        response = self._delete('delete_teacher_upload', attacker, upload.pk)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(TeacherUpload.objects.filter(pk=upload.pk).exists())

    def test_hs_admin_cannot_delete_a_teacher_upload(self):
        from cis.models.teacher import TeacherUpload

        upload = self._teacher_upload()
        attacker = make_user('hsadmin2@example.com', roles=['highschool_admin'])

        response = self._delete('delete_teacher_upload', attacker, upload.pk)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(TeacherUpload.objects.filter(pk=upload.pk).exists())


class HsAdministratorRoleScopeTests(TestCase):
    """
    hsadministratorrole is the one add_new action the HS admin portal uses.
    CE keeps full access; an HS admin is scoped to their own schools.
    """

    def setUp(self):
        self.factory = RequestFactory()

    def _hs_admin_for(self, highschool, email='scoped@example.com'):
        from cis.models.highschool_administrator import (
            HSAdministrator, HSAdministratorPosition, HSPosition,
        )

        user = make_user(email, roles=['highschool_admin'])
        hsadmin = HSAdministrator.objects.create(user=user)
        position = HSPosition.objects.create(name='Counselor')
        HSAdministratorPosition.objects.create(
            hsadmin=hsadmin, highschool=highschool, position=position,
            status='Active',
        )
        return user

    def _highschool(self, name):
        from cis.models.highschool import HighSchool

        return HighSchool.objects.create(name=name, status='Active')

    def test_hs_admin_refused_for_another_school(self):
        mine = self._highschool('Mine HS')
        theirs = self._highschool('Theirs HS')
        user = self._hs_admin_for(mine)

        request = self.factory.post('/highschool_admin/ajax/', {
            'model': 'hsadministratorrole',
            'highschool': str(theirs.id),
            'id': '-1',
        })
        request.user = user

        response = add_new_actions.dispatch(request, 'hsadministratorrole')

        self.assertEqual(response.status_code, 403)

    def test_non_hsadmin_roleless_user_refused(self):
        user = make_user('nobody@example.com', roles=[])

        request = self.factory.post('/highschool_admin/ajax/', {
            'model': 'hsadministratorrole', 'id': '-1',
        })
        request.user = user

        response = add_new_actions.dispatch(request, 'hsadministratorrole')

        self.assertEqual(response.status_code, 403)
