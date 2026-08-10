"""add_new_note dispatches through the note_types registry.

Before this, `cis/views/note.py::add_new_note` picked both the form and the
writer from hardcoded `if request.POST.get('model') == …` chains. A NoteType
registered by another app could not appear in either chain, so it fell through
to the generic NoteForm, matched no writer branch, left `note` as None, and
returned a success-shaped "There was an error while adding note" — the request
looked fine and wrote nothing.

These tests pin the fix: a kind registered from outside this module writes, and
the kinds the chain used to name still behave as they did.
"""
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from cis.models.course import Cohort, Course
from cis.models.customuser import CustomUser
from cis.models.note import CourseNote
from cis.notes import NoteType, note_types
from cis.views.note import add_new_note


def _ce_user():
    user = CustomUser.objects.create_user(
        username='ce-registry@test.test', email='ce-registry@test.test',
        password='pw-for-tests')
    user.groups.add(Group.objects.get_or_create(name='ce')[0])
    return user


class RegistryDispatchTests(TestCase):
    #: Deliberately a slug the old if-chain never contained.
    SLUG = 'registry_only_note'

    def setUp(self):
        self.factory = RequestFactory()
        self.user = _ce_user()
        self.course = Course.objects.create(
            catalog_number='TC101', title='Test Course',
            cohort=Cohort.objects.create(name='Test Subject', designator='TC'),
        )

        note_types.register(NoteType(
            slug=self.SLUG,
            model=CourseNote,
            owner_field='course',
            owner_model=Course,
            permission=lambda user: True,
        ))
        self.addCleanup(note_types._types.pop, self.SLUG, None)

    def _post(self, slug, **overrides):
        payload = {
            'id': '-1',
            'model': slug,
            'add_to': str(self.course.id),
            'note': 'written through the registry',
            'ajax': '1',
        }
        payload.update(overrides)
        request = self.factory.post('/ce/add_new_ajax/', payload)
        request.user = self.user
        return add_new_note(request, 'course')

    def test_a_kind_registered_outside_this_module_actually_writes(self):
        before = CourseNote.objects.count()
        response = self._post(self.SLUG)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            CourseNote.objects.count(), before + 1,
            'the registry-dispatched note was not written',
        )
        self.assertEqual(
            CourseNote.objects.latest('id').note,
            'written through the registry',
        )

    def test_an_unregistered_slug_is_rejected_rather_than_silently_ignored(self):
        before = CourseNote.objects.count()
        response = self._post('no_such_note_kind')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(CourseNote.objects.count(), before)

    def test_a_kind_the_caller_may_not_post_is_refused(self):
        note_types.register(NoteType(
            slug='registry_denied_note',
            model=CourseNote,
            owner_field='course',
            owner_model=Course,
            permission=lambda user: False,
        ))
        self.addCleanup(note_types._types.pop, 'registry_denied_note', None)

        before = CourseNote.objects.count()
        response = self._post('registry_denied_note')

        self.assertEqual(response.status_code, 403)
        self.assertEqual(CourseNote.objects.count(), before)

    def test_cis_own_kinds_still_resolve_to_the_form_the_chain_picked(self):
        """Each slug the old chain named keeps that exact form."""
        from cis.forms.note import (
            ClassSectionNoteForm, EventNoteForm, StudentNoteForm,
            StudentNoteReplyForm, StudentPlanNoteForm,
            TeacherApplicationNoteForm, TeacherNoteForm, VisitReportNoteForm,
        )

        expected = {
            'studentnote': StudentNoteForm,
            'student_replynote': StudentNoteReplyForm,
            'eventnote': EventNoteForm,
            'teachernote': TeacherNoteForm,
            'classsectionnote': ClassSectionNoteForm,
            'teacherapplicationnote': TeacherApplicationNoteForm,
            'studentplannote': StudentPlanNoteForm,
            'visitreportnote': VisitReportNoteForm,
        }
        for slug, form_class in expected.items():
            with self.subTest(slug=slug):
                self.assertIs(note_types.get(slug).form, form_class)

    def test_kinds_the_chain_left_to_the_generic_form_declare_none(self):
        """coursenote/highschoolnote/hsadminnote/ticketnote hit the else."""
        for slug in ('coursenote', 'highschoolnote', 'hsadminnote',
                     'ticketnote'):
            with self.subTest(slug=slug):
                self.assertIsNone(note_types.get(slug).form)

    def test_only_studentplannote_takes_request_in_its_form_init(self):
        takes_request = {
            note_type.slug for note_type in note_types
            if note_type.form_takes_request
        }
        self.assertEqual(takes_request, {'studentplannote'})
