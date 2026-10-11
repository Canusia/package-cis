"""Forms that save to a student use the student the view resolved, never the
posted hidden id (ewu#96)."""
import uuid

from django.contrib.auth.models import Group
from django.http import QueryDict
from django.test import TestCase

from cis.forms.student import ParentConsentForm, StudentAgreementForm, StudentDropRequestForm
from cis.models import CustomUser
from cis.models.course import Campus, Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentDropRequest, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import ParentConsent, Student, StudentAgreement
from cis.models.term import AcademicYear, Term


def _u(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


class ResolvedStudentFormTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        hs = HighSchool.objects.create(name=_u('HS'))
        self.term = Term.objects.create(
            academic_year=AcademicYear.objects.create(name=_u('AY')), code='F32', label=_u('Fall'))
        course = Course.objects.create(
            catalog_number='101', title='Intro', name=_u('COURSE'),
            cohort=Cohort.objects.create(name=_u('Cohort'), designator='PC'),
            credit_hours=3, campus=Campus.objects.create(name=_u('Campus')))
        section = ClassSection.objects.create(
            term=self.term, course=course, class_number=_u('CN'), section_number='01', highschool=hs)

        def student():
            user = CustomUser.objects.create_user(
                username=_u('stu'), email=f'{_u("stu")}@example.com', password='x')
            s = Student.objects.create(user=user, highschool=hs, grade_level='FR')
            reg = StudentRegistration.objects.create(
                student=s, class_section=section, status='applied', status_changed_on={})
            return s, reg

        (self.a, self.reg_a), (self.b, _) = student(), student()
        prefix = __import__('django').conf.settings.CAMPUS_CODE_PREFIX
        Setting.objects.update_or_create(
            key=f'{prefix}_cis_registrations',
            defaults={'value': {'registration_terms': [str(self.term.id)]}})
        Setting.objects.update_or_create(
            key=f'{prefix}_regis_email',
            defaults={'value': {'is_active': 'No',
                                'parent_consent_recv_subject': 'Consent received',
                                'parent_consent_recv': 'Consent received.'}})

    # -- builders: (form, data) per form ----------------------------------
    def consent(self, posted, student='a'):
        return ParentConsentForm(data={'action': 'submit_parent_consent',
                                       'parent_signature': 'A Parent', **posted},
                                 student=getattr(self, student))

    def agreement(self, posted, student='a'):
        return StudentAgreementForm(data={'student_signature': 'A Student', **posted},
                                    student=getattr(self, student))

    def drop(self, posted, student='a'):
        applied = StudentRegistration.objects.filter(student=self.a)
        return StudentDropRequestForm(applied, data={'registration': str(self.reg_a.id),
                                                     'note': 'why', **posted},
                                      student=getattr(self, student))

    BUILDERS = ('consent', 'agreement', 'drop')

    def test_keyword_is_required(self):
        with self.assertRaises(TypeError):
            ParentConsentForm(data={})
        with self.assertRaises(TypeError):
            StudentAgreementForm(data={})
        with self.assertRaises(TypeError):
            StudentDropRequestForm([], data={})

    def test_bound_form_without_a_student_raises(self):
        with self.assertRaises(ValueError):
            ParentConsentForm(data={'parent_signature': 'x'}, student=None)

    def test_unbound_preview_without_a_student_renders(self):
        form = ParentConsentForm(initial={'student': '-1', 'term': '-1'}, student=None)
        self.assertIn('parent_signature', form.as_p())

    def test_posted_other_student_is_invalid(self):
        for name in self.BUILDERS:
            with self.subTest(form=name):
                form = getattr(self, name)({'student': str(self.b.id)})
                self.assertFalse(form.is_valid())
                self.assertTrue(form.has_error('__all__', code='wrong_student'))

    def test_duplicate_values_with_another_student_are_invalid(self):
        data = QueryDict(mutable=True)
        data.update({'action': 'submit_parent_consent', 'parent_signature': 'A Parent'})
        data.setlist('student', [str(self.a.id), str(self.b.id)])
        self.assertFalse(ParentConsentForm(data=data, student=self.a).is_valid())

    def test_missing_or_matching_posted_student_is_valid(self):
        for name in self.BUILDERS:
            for posted in ({}, {'student': str(self.a.id)}):
                with self.subTest(form=name, posted=posted):
                    form = getattr(self, name)(posted)
                    self.assertTrue(form.is_valid(), form.errors)

    def test_saves_go_to_the_resolved_student(self):
        for name in self.BUILDERS:
            form = getattr(self, name)({})
            self.assertTrue(form.is_valid(), form.errors)
            form.save()
        self.assertTrue(ParentConsent.objects.filter(student=self.a).exists())
        self.assertTrue(StudentAgreement.objects.filter(student=self.a).exists())
        self.assertTrue(StudentDropRequest.objects.filter(student=self.a).exists())
        self.assertFalse(ParentConsent.objects.filter(student=self.b).exists())
        self.assertFalse(StudentAgreement.objects.filter(student=self.b).exists())
        self.assertFalse(StudentDropRequest.objects.filter(student=self.b).exists())

    def test_drop_form_with_invalid_registration_is_a_form_error(self):
        form = self.drop({'registration': ''})
        self.assertFalse(form.is_valid())
        self.assertTrue(form.has_error('registration'))
