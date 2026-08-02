"""Campus gate for the CE index pages added in this change:
credentials (expiry + summary), FAAs, recommendations, supporting docs,
transactions, and notes. A ce user must only see records for the campuses they
process (via the record's course/campus, or the student's applied-at campus);
superusers and non-ce roles are unscoped. Unverified students and null-student
notes stay universally visible.
"""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from rest_framework.test import APIRequestFactory

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.term import AcademicYear, Term
from cis.models.course import Campus, Cohort, Course
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import (
    Student, StudentRecommendation, StudentSupportingDocument,
    StudentTuitionAssistance,
)
from cis.models.note import StudentNote
from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate
from cis.views.credentials import CredentialExpiryViewSet, CredentialSummaryViewSet
from cis.views.student import (
    StudentRecommendationViewSet, StudentTuitionAssistanceViewSet,
    StudentSupportingDocumentViewSet, StudentNoteViewSet, StudentViewSet,
)
from student_transactions.models import StudentTransaction

import importlib.util as _il
if _il.find_spec('student_transactions.student_transactions'):
    from student_transactions.student_transactions.views.api.viewsets import StudentTransactionViewSet
else:
    from student_transactions.views.api.viewsets import StudentTransactionViewSet

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class CampusGatePagesTests(TestCase):
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
        Group.objects.get_or_create(name='instructor')
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

        self.stu_a = self._student(verified=True, section=self.sec_a)
        self.stu_b = self._student(verified=True, section=self.sec_b)
        self.stu_unverified = self._student(verified=False, section=None)

        self.ce = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.ce.campus = {'process_campus': [str(self.campus_a.id)]}
        self.ce.save()

        self.superuser = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')

    def _student(self, verified, section):
        u = User.objects.create_user(
            username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        student = Student.objects.create(user=u, account_verified=verified)
        if section is not None:
            StudentRegistration.objects.create(
                student=student, class_section=section,
                status_changed_on={'applied_on': '01/01/2024'})
        return student

    def _qs(self, viewset_cls, user, **params):
        request = APIRequestFactory().get('/x', params)
        request.user = user
        vs = viewset_cls()
        vs.request = request
        return vs.get_queryset()

    # --- helper matrix (drives all student-backed viewsets) ------------------
    def test_helper_scopes_students_for_ce_but_not_superuser(self):
        from cis.campus_gate import scope_records_by_student_campus
        ra = StudentRecommendation.objects.create(student=self.stu_a, term=self.term, recommendation={})
        rb = StudentRecommendation.objects.create(student=self.stu_b, term=self.term, recommendation={})
        ru = StudentRecommendation.objects.create(
            student=self.stu_unverified, term=self.term, recommendation={})

        ce_qs = scope_records_by_student_campus(
            StudentRecommendation.objects.all(), self.ce)
        self.assertIn(ra, ce_qs)      # applied at accessible campus A
        self.assertIn(ru, ce_qs)      # unverified student -> universal
        self.assertNotIn(rb, ce_qs)   # applied only at campus B

        su_qs = scope_records_by_student_campus(
            StudentRecommendation.objects.all(), self.superuser)
        self.assertIn(rb, su_qs)      # superuser unscoped

    # --- student-backed viewsets --------------------------------------------
    def test_recommendation_viewset_scoped(self):
        ra = StudentRecommendation.objects.create(student=self.stu_a, term=self.term, recommendation={})
        rb = StudentRecommendation.objects.create(student=self.stu_b, term=self.term, recommendation={})
        qs = self._qs(StudentRecommendationViewSet, self.ce)
        self.assertIn(ra, qs)
        self.assertNotIn(rb, qs)
        self.assertIn(rb, self._qs(StudentRecommendationViewSet, self.superuser))

    def test_faa_viewset_scoped(self):
        fa = StudentTuitionAssistance.objects.create(student=self.stu_a, term=self.term)
        fb = StudentTuitionAssistance.objects.create(student=self.stu_b, term=self.term)
        qs = self._qs(StudentTuitionAssistanceViewSet, self.ce)
        self.assertIn(fa, qs)
        self.assertNotIn(fb, qs)

    def test_support_doc_viewset_scoped(self):
        da = StudentSupportingDocument.objects.create(student=self.stu_a, term=self.term)
        db = StudentSupportingDocument.objects.create(student=self.stu_b, term=self.term)
        qs = self._qs(StudentSupportingDocumentViewSet, self.ce)
        self.assertIn(da, qs)
        self.assertNotIn(db, qs)

    def test_support_doc_campus_dropdown_narrows(self):
        # A ce user with BOTH campuses; the dropdown `campus` param narrows to one.
        both = self._ce_user([str(self.campus_a.id), str(self.campus_b.id)])
        da = StudentSupportingDocument.objects.create(student=self.stu_a, term=self.term)
        db = StudentSupportingDocument.objects.create(student=self.stu_b, term=self.term)

        all_qs = self._qs(StudentSupportingDocumentViewSet, both)
        self.assertIn(da, all_qs)
        self.assertIn(db, all_qs)

        a_qs = self._qs(StudentSupportingDocumentViewSet, both,
                        campus=str(self.campus_a.id))
        self.assertIn(da, a_qs)
        self.assertNotIn(db, a_qs)

    def test_transaction_viewset_scoped(self):
        ta = StudentTransaction.objects.create(student=self.stu_a, term=self.term)
        tb = StudentTransaction.objects.create(student=self.stu_b, term=self.term)
        qs = self._qs(StudentTransactionViewSet, self.ce)
        self.assertIn(ta, qs)
        self.assertNotIn(tb, qs)

    def test_students_dirty_tab_scoped_by_campus(self):
        # The /ce/students/ #dirty tab is StudentViewSet with record_type=dirty;
        # dirty students must still be campus-scoped for a ce user.
        Student.objects.filter(pk__in=[self.stu_a.pk, self.stu_b.pk]).update(
            profile_dirty_at='2024-01-01T00:00:00Z')
        qs = self._qs(StudentViewSet, self.ce, record_type='dirty')
        self.assertIn(self.stu_a, qs)      # applied at campus A (accessible)
        self.assertNotIn(self.stu_b, qs)   # applied only at campus B

    def test_note_viewset_scoped_and_keeps_null_student(self):
        meta = {'type': 'general'}
        na = StudentNote.objects.create(student=self.stu_a, createdby=self.ce, meta=meta)
        nb = StudentNote.objects.create(student=self.stu_b, createdby=self.ce, meta=meta)
        n_null = StudentNote.objects.create(student=None, createdby=self.ce, meta=meta)
        qs = self._qs(StudentNoteViewSet, self.ce)
        self.assertIn(na, qs)
        self.assertNotIn(nb, qs)
        self.assertIn(n_null, qs)  # null-student notes stay visible

    # --- credentials (campus via course) ------------------------------------
    def _certificate(self, course):
        hs = HighSchool.objects.create(name=f'HS-{_sfx()}')
        tu = User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x')
        teacher = Teacher.objects.create(user=tu)
        th = TeacherHighSchool.objects.create(teacher=teacher, highschool=hs)
        return TeacherCourseCertificate.objects.create(
            teacher_highschool=th, course=course)

    def _ce_user(self, campus_ids):
        u = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        u.groups.add(Group.objects.get_or_create(name='ce')[0])
        u.campus = {'process_campus': campus_ids}
        u.save()
        return u

    def test_credential_expiry_viewset_scoped(self):
        ca = self._certificate(self.course_a)
        cb = self._certificate(self.course_b)
        qs = self._qs(CredentialExpiryViewSet, self.ce)  # ce scoped to campus A
        self.assertIn(ca, qs)
        self.assertNotIn(cb, qs)
        # a ce user scoped to campus B sees the mirror image (proves the scope
        # narrows to the user's own campuses, not just hides everything).
        qs_b = self._qs(CredentialExpiryViewSet, self._ce_user([str(self.campus_b.id)]))
        self.assertIn(cb, qs_b)
        self.assertNotIn(ca, qs_b)

    def test_credential_expiry_campus_dropdown_narrows(self):
        both = self._ce_user([str(self.campus_a.id), str(self.campus_b.id)])
        ca = self._certificate(self.course_a)
        cb = self._certificate(self.course_b)
        both_qs = self._qs(CredentialExpiryViewSet, both)
        self.assertIn(ca, both_qs)
        self.assertIn(cb, both_qs)
        a_qs = self._qs(CredentialExpiryViewSet, both, campus=str(self.campus_a.id))
        self.assertIn(ca, a_qs)
        self.assertNotIn(cb, a_qs)

    def test_credential_summary_viewset_scoped(self):
        self._certificate(self.course_a)
        self._certificate(self.course_b)
        ce_total = sum(r['count'] for r in self._qs(CredentialSummaryViewSet, self.ce))
        su_total = sum(
            r['count'] for r in self._qs(CredentialSummaryViewSet, self.superuser))
        self.assertEqual(ce_total, 1)   # only the campus-A certificate
        self.assertEqual(su_total, 2)   # superuser sees both
