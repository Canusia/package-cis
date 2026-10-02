"""School pickers offer the current campus's Active schools only."""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from cis.campus_context import campus_context, deployment_campus
from cis.forms.application_fields import build_fields
from cis.forms.highschool import HighSchoolOfferingLookupForm
from cis.forms.section import (
    AddNewStudentRegistrationForm, HighSchoolClassOfferingForm)
from cis.forms.student_import import StudentImportRowForm
from cis.forms.teacher import TeacherHighSchoolForm
from cis.forms.teacher_applicant import EditSchoolCourseForm
from cis.models.course import Campus
from cis.models.highschool import HighSchool, HighSchoolCampus


def _campus():
    return Campus.objects.create(
        name=f'C-{uuid.uuid4().hex[:8]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}_{uuid.uuid4().hex[:6]}')


def _hs(name):
    hs = HighSchool.objects.create(name=name, code=uuid.uuid4().hex[:8])
    HighSchoolCampus.objects.filter(highschool=hs).delete()
    return hs


def _link(hs, campus, status='Active'):
    return HighSchoolCampus.objects.create(
        highschool=hs, campus=campus, building_code=uuid.uuid4().hex[:6],
        status=status)


def _ids(field):
    return {str(o.pk) for o in field.queryset}


class _Base(TestCase):
    def setUp(self):
        self.a, self.b = _campus(), _campus()
        self.here = _hs('Here HS')
        self.inactive = _hs('Inactive HS')
        self.foreign = _hs('Foreign HS')
        _link(self.here, self.a)
        _link(self.inactive, self.a, 'Inactive')
        _link(self.foreign, self.b)

    def _builders(self):
        """(label, factory(data=None) -> form, field name)."""
        return [
            ('teacher', lambda d=None: TeacherHighSchoolForm(
                '-1', str(uuid.uuid4()), 'y', data=d), 'highschool'),
            ('section_offering', lambda d=None: HighSchoolClassOfferingForm(
                data=d), 'highschool'),
            ('registration', lambda d=None: AddNewStudentRegistrationForm(
                data=d), 'highschool'),
            ('lookup', lambda d=None: HighSchoolOfferingLookupForm(
                data=d), 'highschool'),
            ('student_import', lambda d=None: StudentImportRowForm(
                data=d), 'highschool'),
        ]


@override_settings(MULTI_CAMPUS=True)
class MultiCampusPickerTests(_Base):
    def test_excludes_other_campus_and_inactive(self):
        with campus_context(self.a):
            for label, make, name in self._builders():
                ids = _ids(make().fields[name])
                self.assertIn(str(self.here.pk), ids, label)
                self.assertNotIn(str(self.foreign.pk), ids, label)
                self.assertNotIn(str(self.inactive.pk), ids, label)

    def test_other_campus_sees_its_own(self):
        with campus_context(self.b):
            for label, make, name in self._builders():
                self.assertEqual(
                    _ids(make().fields[name]), {str(self.foreign.pk)}, label)

    def test_post_of_foreign_school_is_invalid(self):
        with campus_context(self.a):
            form = HighSchoolClassOfferingForm(
                data={'highschool': [str(self.foreign.pk)]})
            self.assertFalse(form.is_valid())
            self.assertIn('highschool', form.errors)
            form = HighSchoolClassOfferingForm(
                data={'highschool': [str(self.here.pk)]})
            self.assertTrue(form.is_valid(), form.errors)

            form = TeacherHighSchoolForm(
                '-1', str(uuid.uuid4()), 'y',
                data={'highschool': str(self.foreign.pk), 'status': 'Active'})
            self.assertFalse(form.is_valid())
            self.assertIn('highschool', form.errors)

    def test_registration_form_rejects_foreign_school(self):
        with campus_context(self.a):
            field = AddNewStudentRegistrationForm().fields['highschool']
            with self.assertRaises(ValidationError):
                field.clean(str(self.foreign.pk))
            self.assertEqual(field.clean(str(self.here.pk)), self.here)

    def test_student_import_ignores_foreign_school_by_ceeb(self):
        self.foreign.code = 'FOREIGN1'
        self.foreign.save()
        self.here.code = 'HERE1'
        self.here.save()
        with campus_context(self.a):
            form = StudentImportRowForm(data={'highschool_ceeb': 'FOREIGN1'})
            form.is_valid()
            self.assertIsNone(form.cleaned_data.get('highschool'))
            form = StudentImportRowForm(data={'highschool_ceeb': 'HERE1'})
            form.is_valid()
            self.assertEqual(form.cleaned_data.get('highschool'), self.here)

    def test_applicant_form_keeps_current_school(self):
        class _App:
            id = uuid.uuid4()
            highschool = None
            highschool_id = self.foreign.pk
        with campus_context(self.a):
            form = EditSchoolCourseForm(_App())
            ids = {str(v) for v, _ in form.fields['highschool'].choices if v}
            self.assertEqual(ids, {str(self.here.pk), str(self.foreign.pk)})
            ids = {str(v) for v, _ in EditSchoolCourseForm().fields[
                'highschool'].choices if v}
            self.assertEqual(ids, {str(self.here.pk)})

    def test_model_choice_application_field_scoped_and_keeps(self):
        entry = {
            'name': 'highschool', 'type': 'model_choice', 'target': 'skip',
            'label': 'HS',
            'queryset': 'cis.models.highschool.HighSchool.objects.all',
        }

        class _Student:
            highschool_id = self.foreign.pk
        with campus_context(self.a):
            (_, field), = build_fields(entry, {})
            self.assertEqual(_ids(field), {str(self.here.pk)})
            (_, field), = build_fields(entry, {'student': _Student()})
            self.assertEqual(
                _ids(field), {str(self.here.pk), str(self.foreign.pk)})


@override_settings(MULTI_CAMPUS=False)
class SingleCampusPickerTests(TestCase):
    def test_options_are_the_active_linked_schools(self):
        campus = deployment_campus() or _campus()
        shown, hidden = _hs('Shown'), _hs('Hidden')
        _link(shown, campus)
        _link(hidden, campus, 'Inactive')
        for label, make, name in _Base._builders(None):
            ids = _ids(make().fields[name])
            self.assertIn(str(shown.pk), ids, label)
            self.assertNotIn(str(hidden.pk), ids, label)
