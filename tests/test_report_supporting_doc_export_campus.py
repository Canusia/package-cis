"""Campus gate for the supporting_doc_export report: a ce requester's export
only includes StudentSupportingDocument records for students who applied at
their processable campuses (via student -> studentregistration ->
class_section -> course -> campus), optionally narrowed to a selected campus.
Superusers are unscoped.
"""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, RequestFactory

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.term import AcademicYear, Term
from cis.models.course import Campus, Cohort, Course
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student, StudentSupportingDocument
from cis.reports.supporting_doc_export import supporting_doc_export

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class SupportingDocExportReportCampusTests(TestCase):
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
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@x.com'})

        self.ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.term = Term.objects.create(
            academic_year=self.ay, code='FA', label=f'Fall-{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.course_a = Course.objects.create(
            catalog_number='101', title='A', cohort=self.cohort, campus=self.campus_a)
        self.course_b = Course.objects.create(
            catalog_number='102', title='B', cohort=self.cohort, campus=self.campus_b)
        self.sec_a = ClassSection.objects.create(
            class_number='1001', term=self.term, course=self.course_a)
        self.sec_b = ClassSection.objects.create(
            class_number='1002', term=self.term, course=self.course_b)

        self.doc_a = self._doc_at(self.sec_a)
        self.doc_b = self._doc_at(self.sec_b)

        self.ce = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.ce.campus = {'process_campus': [str(self.campus_a.id)]}
        self.ce.save()
        self.superuser = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')

    def _doc_at(self, section):
        u = User.objects.create_user(
            username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        student = Student.objects.create(user=u, account_verified=True)
        StudentRegistration.objects.create(
            student=student, class_section=section, status='applied',
            status_changed_on={'applied_on': '01/01/2024'})
        return StudentSupportingDocument.objects.create(
            student=student, term=self.term,
            media=SimpleUploadedFile(f'{_sfx()}.pdf', b'data'))

    def _data(self, campus):
        return {
            'term': [str(self.term.id)],
            'uploaded_on_from': [None],
            'uploaded_on_until': [None],
            'campus': campus,
        }

    def test_campus_field_is_required_multiselect_of_accessible(self):
        from django import forms as dj_forms
        req = RequestFactory().get('/')
        req.user = self.ce
        form = supporting_doc_export(req)
        # campus is the FIRST field, required, and a multi-select.
        self.assertEqual(list(form.fields)[0], 'campus')
        self.assertIsInstance(
            form.fields['campus'], dj_forms.ModelMultipleChoiceField)
        self.assertTrue(form.fields['campus'].required)
        qs = form.fields['campus'].queryset
        self.assertIn(self.campus_a, qs)
        self.assertNotIn(self.campus_b, qs)

    def test_ce_result_scoped_to_selected_own_campus(self):
        report = supporting_doc_export()
        qs = report.get_result(
            self._data(campus=[str(self.campus_a.id)]), user=self.ce)
        self.assertIn(self.doc_a, qs)
        self.assertNotIn(self.doc_b, qs)

    def test_ce_cannot_widen_to_inaccessible_campus(self):
        # selecting A (accessible) + B (not) keeps only A's document.
        report = supporting_doc_export()
        qs = report.get_result(
            self._data(campus=[str(self.campus_a.id), str(self.campus_b.id)]),
            user=self.ce)
        self.assertIn(self.doc_a, qs)
        self.assertNotIn(self.doc_b, qs)

    def test_ce_only_inaccessible_selection_returns_none(self):
        report = supporting_doc_export()
        qs = report.get_result(
            self._data(campus=[str(self.campus_b.id)]), user=self.ce)
        self.assertNotIn(self.doc_a, qs)
        self.assertNotIn(self.doc_b, qs)

    def test_superuser_uses_selection_as_is(self):
        report = supporting_doc_export()
        qs = report.get_result(
            self._data(campus=[str(self.campus_b.id)]), user=self.superuser)
        self.assertIn(self.doc_b, qs)
        self.assertNotIn(self.doc_a, qs)
