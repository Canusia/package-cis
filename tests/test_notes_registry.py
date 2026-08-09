"""
Tests for the note-type registry behind /ce/add_new_ajax/.

Covers the three things the refactor is for: every note kind is declared once,
another app can add its own, and each kind states who may post it — including
student_replynote, which the HS admin portal posts and which had no role check
and no school scoping before.
"""
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from cis.models.customuser import CustomUser
from cis.notes import NoteRegistry, NoteType, note_types
from cis.actions.registry import add_new_actions

ROLES = [
    'applicant', 'ce', 'district_admin', 'faculty',
    'highschool_admin', 'instructor', 'student', 'speaker',
]

CE_ONLY_NOTES = [
    'coursenote', 'highschoolnote', 'studentnote', 'hsadminnote',
    'teachernote',
]

ALL_NOTES = CE_ONLY_NOTES + [
    'classsectionnote', 'eventnote', 'studentplannote', 'student_replynote',
    'ticketnote', 'teacherapplicationnote', 'visitreportnote',
]


def make_user(email, roles=()):
    for name in ROLES:
        Group.objects.get_or_create(name=name)
    user = CustomUser.objects.create(
        username=email, email=email, first_name='Test', last_name='User',
    )
    for role in roles:
        user.groups.add(Group.objects.get(name=role))
    return user


class RegistryShapeTests(TestCase):

    def test_every_note_kind_is_declared_once(self):
        for slug in ALL_NOTES:
            with self.subTest(slug=slug):
                self.assertIn(slug, note_types)

    def test_each_kind_declares_a_permission(self):
        for note_type in note_types:
            with self.subTest(slug=note_type.slug):
                self.assertTrue(callable(note_type.permission))

    def test_each_kind_is_dispatchable_as_an_action(self):
        registered = set()
        for group in add_new_actions._groups.values():
            registered.update(group['actions'].keys())
        for slug in ALL_NOTES:
            with self.subTest(slug=slug):
                self.assertIn(slug, registered)

    def test_another_app_can_register_its_own_note_type(self):
        """The extension point: registration is not cis-only."""
        from cis.models.course import Course
        from cis.models.note import CourseNote

        registry = NoteRegistry()
        registry.register(NoteType(
            slug='thirdpartynote', model=CourseNote,
            owner_field='course', owner_model=Course,
        ))

        self.assertIn('thirdpartynote', registry)
        self.assertEqual(registry.get('thirdpartynote').model, CourseNote)

    def test_re_registering_a_slug_replaces_it(self):
        from cis.models.course import Course
        from cis.models.note import CourseNote, EventNote

        registry = NoteRegistry()
        registry.register(NoteType(slug='dupe', model=CourseNote,
                                   owner_field='course', owner_model=Course))
        registry.register(NoteType(slug='dupe', model=EventNote,
                                   owner_field='course', owner_model=Course))

        self.assertEqual(registry.get('dupe').model, EventNote)


class NotePermissionTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

    def _dispatch(self, slug, user):
        request = self.factory.post('/ce/add_new_ajax/', {'model': slug})
        request.user = user
        return add_new_actions.dispatch(request, slug)

    def test_student_is_refused_ce_only_notes(self):
        user = make_user('student@example.com', roles=['student'])
        for slug in CE_ONLY_NOTES:
            with self.subTest(slug=slug):
                self.assertEqual(self._dispatch(slug, user).status_code, 403)

    def test_hs_admin_is_refused_ce_only_notes(self):
        user = make_user('hsadmin@example.com', roles=['highschool_admin'])
        for slug in CE_ONLY_NOTES:
            with self.subTest(slug=slug):
                self.assertEqual(self._dispatch(slug, user).status_code, 403)

    def test_instructor_may_post_class_section_notes(self):
        user = make_user('instructor@example.com', roles=['instructor'])
        note_type = note_types.get('classsectionnote')
        self.assertTrue(note_type.permission(user))

    def test_ticket_notes_stay_open_to_ticket_participants(self):
        """support_ticket posts these from student/instructor/hs_admin views."""
        note_type = note_types.get('ticketnote')
        for role in ['student', 'instructor', 'highschool_admin', 'ce']:
            with self.subTest(role=role):
                user = make_user(f'ticket-{role}@example.com', roles=[role])
                self.assertTrue(note_type.permission(user))

    def test_faculty_may_post_event_notes(self):
        """pd_event exposes the event detail page from its faculty urls too."""
        user = make_user('faculty@example.com', roles=['faculty'])
        self.assertTrue(note_types.get('eventnote').permission(user))

    def test_hs_admin_may_post_student_plan_notes(self):
        """degree_pathway posts this from its hs_admin detail page."""
        user = make_user('plan-admin@example.com', roles=['highschool_admin'])
        self.assertTrue(note_types.get('studentplannote').permission(user))

    def test_roleless_user_is_refused_ce_only_notes(self):
        user = make_user('noroles@example.com', roles=[])
        for slug in CE_ONLY_NOTES:
            with self.subTest(slug=slug):
                self.assertEqual(self._dispatch(slug, user).status_code, 403)


class StudentReplyScopeTests(TestCase):
    """
    The HS admin "Reply to Note" path. Before the registry it had neither a
    role check nor school scoping, so a reply could be posted against any
    student UUID.
    """

    def setUp(self):
        self.factory = RequestFactory()

    def _highschool(self, name):
        from cis.models.highschool import HighSchool

        return HighSchool.objects.create(name=name, status='Active')

    def _student_at(self, highschool, email):
        from cis.models.student import Student

        user = make_user(email, roles=['student'])
        return Student.objects.create(user=user, highschool=highschool)

    def _hs_admin_for(self, highschool, email):
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

    def _may_reply(self, user, student):
        request = self.factory.post('/highschool_admin/ajax/', {
            'model': 'student_replynote',
            'add_to': str(student.id),
        })
        request.user = user
        return note_types.get('student_replynote').may(request)

    def test_hs_admin_may_reply_for_their_own_student(self):
        mine = self._highschool('Mine HS')
        student = self._student_at(mine, 'mine-student@example.com')
        user = self._hs_admin_for(mine, 'mine-admin@example.com')

        self.assertTrue(self._may_reply(user, student))

    def test_hs_admin_refused_for_a_student_at_another_school(self):
        mine = self._highschool('Mine HS')
        theirs = self._highschool('Theirs HS')
        student = self._student_at(theirs, 'their-student@example.com')
        user = self._hs_admin_for(mine, 'other-admin@example.com')

        self.assertFalse(self._may_reply(user, student))

    def test_ce_may_reply_for_any_student(self):
        theirs = self._highschool('Any HS')
        student = self._student_at(theirs, 'any-student@example.com')
        ce = make_user('ce-user@example.com', roles=['ce'])

        self.assertTrue(self._may_reply(ce, student))

    def test_student_role_is_refused_outright(self):
        hs = self._highschool('Some HS')
        student = self._student_at(hs, 'self-student@example.com')
        other = make_user('nosy@example.com', roles=['student'])

        self.assertFalse(self._may_reply(other, student))
