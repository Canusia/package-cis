"""Regression coverage for the three EditStudentRegistration call sites in
`cis.views.registration.manage_registration`.

The tenant form (`myce_tenant_configs/services/registration_form.py`) takes the
registration it is editing as its first positional argument. Three branches in
manage_registration still used the pre-refactor signature and raised before
doing any work; two of them also skipped the campus-permission gate and the
audit notes that `EditStudentRegistration.save()` writes.

Covered here:
  - GET renders and seeds the form from the record
  - a grade change goes through form.save() and writes both audit notes
  - the edit branch refuses a ce user who may not process the campus
  - the delete branch removes the record and writes the student note
  - the delete branch refuses a ce user who may not process the campus
  - a malformed (non-UUID) id is an error response, not a 500
"""
import json
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase, RequestFactory

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import Campus, Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.note import ClassSectionNote, StudentNote
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import Student
from cis.models.term import AcademicYear, Term
from cis.services.tenant_services import get_tenant_service
from cis.views.registration import manage_registration

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class ManageRegistrationTests(TestCase):
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
        self.factory = RequestFactory()
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@x.com'})

        # The form builds its grade choices from this setting; without it the
        # only choice is '-' and the grade-change path cannot be exercised.
        Setting.objects.update_or_create(
            key=getattr(settings, 'CAMPUS_CODE_PREFIX') + '_class_grades',
            defaults={'value': {'grades': 'A,B,C'}},
        )

        self.campus = Campus.objects.create(
            name=f'C-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.term = Term.objects.create(
            academic_year=self.ay, code='FA', label=f'Fall-{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.course = Course.objects.create(
            catalog_number='101', title='A', cohort=self.cohort, campus=self.campus)
        self.section = ClassSection.objects.create(
            class_number='1001', term=self.term, course=self.course)
        self.highschool = HighSchool.objects.create(name=f'HS-{_sfx()}')

        student_user = User.objects.create_user(
            username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        self.student = Student.objects.create(user=student_user, account_verified=True)
        self.registration = StudentRegistration.objects.create(
            student=self.student,
            class_section=self.section,
            highschool=self.highschool,
            status='applied',
            verification_status='pending',
            grade='A',
            status_changed_on={'applied_on': '01/01/2024'},
        )

        self.ce = self._ce_user(process_campus=[str(self.campus.id)])
        self.ce_other_campus = self._ce_user(process_campus=[str(uuid.uuid4())])

    def _ce_user(self, process_campus):
        user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        user.groups.add(Group.objects.get_or_create(name='ce')[0])
        user.campus = {'process_campus': process_campus}
        user.save()
        return user

    def _edit_post(self, **overrides):
        data = {
            'id': str(self.registration.id),
            'status': 'applied',
            'verification_status': 'pending',
            'highschool': str(self.highschool.id),
            'grade': 'A',
            'pay_type': '',
            'registration_type': '',
            'non_student_pay_amount': '0.00',
        }
        data.update(overrides)
        return data

    def _post(self, user, data):
        request = self.factory.post('/ce/add_new_ajax/', data)
        request.user = user
        return manage_registration(request)

    # ---- GET branch ----------------------------------------------------

    def test_get_renders_and_seeds_the_form(self):
        request = self.factory.get(
            '/ce/add_new_ajax/',
            {'id': str(self.registration.id), 'parent': str(self.student.id)},
        )
        request.user = self.ce

        # Pre-fix this raised TypeError: __init__() missing 1 required
        # positional argument: 'student_registration'.
        response = manage_registration(request)

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        # The form seeds its fields from the record, so the rendered widgets
        # carry the registration's own id / status / grade.
        self.assertIn(str(self.registration.id), html)
        self.assertIn('value="applied"', html)
        self.assertIn('value="A"', html)

    def test_get_form_is_seeded_from_the_record(self):
        form = get_tenant_service('registration_form').EditStudentRegistration(
            self.registration)

        self.assertEqual(str(form.fields['id'].initial), str(self.registration.id))
        self.assertEqual(form.fields['status'].initial, 'applied')
        self.assertEqual(form.fields['grade'].initial, 'A')
        self.assertEqual(form.fields['verification_status'].initial, 'pending')

    # ---- edit branch ---------------------------------------------------

    def test_edit_saves_grade_change_with_audit_notes(self):
        student_notes_before = StudentNote.objects.filter(student=self.student).count()
        section_notes_before = ClassSectionNote.objects.filter(
            class_section=self.section).count()

        response = self._post(self.ce, self._edit_post(grade='B'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['status'], 'success')

        self.registration.refresh_from_db()
        self.assertEqual(self.registration.grade, 'B')

        self.assertEqual(
            ClassSectionNote.objects.filter(class_section=self.section).count(),
            section_notes_before + 1)
        self.assertEqual(
            StudentNote.objects.filter(student=self.student).count(),
            student_notes_before + 1)
        self.assertIn(
            'Changing grade from A => B',
            ClassSectionNote.objects.filter(
                class_section=self.section).latest('id').note)

    def test_edit_refused_without_campus_permission(self):
        response = self._post(self.ce_other_campus, self._edit_post(grade='B'))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)['status'], 'error')

        self.registration.refresh_from_db()
        self.assertEqual(self.registration.grade, 'A')

    # ---- delete branch -------------------------------------------------

    def test_delete_removes_registration_and_writes_note(self):
        response = self._post(self.ce, {
            'action': 'delete_registration',
            'id': str(self.registration.id),
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            StudentRegistration.objects.filter(pk=self.registration.id).exists())
        # Assert on the specific note rather than a count — deleting a
        # registration also fires the tenant's own bookkeeping note.
        self.assertEqual(
            StudentNote.objects.filter(
                student=self.student,
                note__startswith='Deleted registration for').count(),
            1)

    def test_delete_refused_without_campus_permission(self):
        response = self._post(self.ce_other_campus, {
            'action': 'delete_registration',
            'id': str(self.registration.id),
        })

        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            StudentRegistration.objects.filter(pk=self.registration.id).exists())

    # ---- input guard ---------------------------------------------------

    def test_malformed_id_is_an_error_not_a_500(self):
        response = self._post(self.ce, {
            'action': 'delete_registration',
            'id': 'not-a-uuid',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['status'], 'error')
        self.assertTrue(
            StudentRegistration.objects.filter(pk=self.registration.id).exists())
