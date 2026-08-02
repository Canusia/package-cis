"""Campus gate for /ce/students/ — a student is scoped to the campuses they
applied at (via registration -> class_section -> course -> campus); unverified
students (account_verified=False) are universally visible/actionable."""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase, RequestFactory
from django.urls import reverse

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.term import AcademicYear, Term
from cis.models.course import Campus, Cohort, Course
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.campus_gate import (
    scope_students_by_campus,
    can_access_student,
    processable_student_ids,
)

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class _NoLoginSignal(TestCase):
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


class StudentCampusScopeTests(_NoLoginSignal):
    def setUp(self):
        # Student.save() looks up Group(name='student'); the StudentRegistration
        # post_save add_note falls back to CustomUser(username='cron').
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

        # verified student who applied at campus A
        self.stu_a = self._student(verified=True)
        StudentRegistration.objects.create(
            student=self.stu_a, class_section=self.sec_a,
            status_changed_on={'applied_on': '01/01/2024'})
        # verified student who applied at campus B
        self.stu_b = self._student(verified=True)
        StudentRegistration.objects.create(
            student=self.stu_b, class_section=self.sec_b,
            status_changed_on={'applied_on': '01/01/2024'})
        # unverified student, no application anywhere
        self.stu_unverified = self._student(verified=False)

        self.user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.user.campus = {'process_campus': [str(self.campus_a.id)]}
        self.user.save()

    def _student(self, verified):
        u = User.objects.create_user(
            username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        return Student.objects.create(user=u, account_verified=verified)

    # --- scope_students_by_campus -------------------------------------------
    def test_scope_includes_applied_and_unverified_excludes_other(self):
        qs = scope_students_by_campus(Student.objects.all(), self.user)
        self.assertIn(self.stu_a, qs)             # applied at A (accessible)
        self.assertIn(self.stu_unverified, qs)    # unverified -> universal
        self.assertNotIn(self.stu_b, qs)          # applied only at B

    def test_scope_selected_campus_narrows_but_keeps_unverified(self):
        # selecting campus_b (which the user cannot process) must NOT widen:
        # it falls back to the user's accessible set.
        qs = scope_students_by_campus(
            Student.objects.all(), self.user, selected_campus=str(self.campus_b.id))
        self.assertIn(self.stu_a, qs)
        self.assertNotIn(self.stu_b, qs)
        self.assertIn(self.stu_unverified, qs)

    def test_scope_no_duplicate_rows(self):
        # two applications at accessible campuses (different sections) must not
        # duplicate the student in the result.
        sec_a2 = ClassSection.objects.create(
            class_number='1003', term=self.term, course=self.course_a)
        StudentRegistration.objects.create(
            student=self.stu_a, class_section=sec_a2,
            status_changed_on={'applied_on': '02/02/2024'})
        qs = scope_students_by_campus(Student.objects.all(), self.user)
        self.assertEqual(list(qs).count(self.stu_a), 1)

    def test_scope_noop_for_non_ce(self):
        instructor = User.objects.create_user(
            username=f'inst_{_sfx()}', email=f'inst_{_sfx()}@x.com', password='x')
        instructor.groups.add(Group.objects.get_or_create(name='instructor')[0])
        qs = scope_students_by_campus(Student.objects.all(), instructor)
        self.assertIn(self.stu_b, qs)  # not campus-filtered

    # --- can_access_student --------------------------------------------------
    def test_can_access_applied_campus(self):
        self.assertTrue(can_access_student(self.user, self.stu_a))

    def test_cannot_access_other_campus(self):
        self.assertFalse(can_access_student(self.user, self.stu_b))

    def test_can_access_unverified(self):
        self.assertTrue(can_access_student(self.user, self.stu_unverified))

    def test_non_ce_cannot_access(self):
        instructor = User.objects.create_user(
            username=f'inst2_{_sfx()}', email=f'inst2_{_sfx()}@x.com', password='x')
        instructor.groups.add(Group.objects.get_or_create(name='instructor')[0])
        self.assertFalse(can_access_student(instructor, self.stu_a))

    # --- processable_student_ids --------------------------------------------
    def test_processable_ids_keeps_applied_and_unverified(self):
        result = processable_student_ids(
            [str(self.stu_a.id), str(self.stu_b.id),
             str(self.stu_unverified.id), 'not-a-uuid'], self.user)
        self.assertIn(str(self.stu_a.id), result)
        self.assertIn(str(self.stu_unverified.id), result)
        self.assertNotIn(str(self.stu_b.id), result)
        self.assertNotIn('not-a-uuid', result)


class StudentCampusGateViewTests(_NoLoginSignal):
    """Integration tests: campus gate wired into /ce/students/ views."""

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

        # verified student who applied at campus A (in scope)
        self.stu_a = self._student(verified=True)
        StudentRegistration.objects.create(
            student=self.stu_a, class_section=self.sec_a,
            status_changed_on={'applied_on': '01/01/2024'})
        # verified student who applied at campus B (out of scope)
        self.stu_b = self._student(verified=True)
        StudentRegistration.objects.create(
            student=self.stu_b, class_section=self.sec_b,
            status_changed_on={'applied_on': '01/01/2024'})
        # unverified student, no application anywhere (universal)
        self.stu_unverified = self._student(verified=False)

        self.user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.user.campus = {'process_campus': [str(self.campus_a.id)]}
        self.user.save()

        self.factory = RequestFactory()
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.user)

    def _student(self, verified):
        u = User.objects.create_user(
            username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        return Student.objects.create(user=u, account_verified=verified)

    # 1. Viewset scope --------------------------------------------------------
    def test_viewset_scopes_to_applied_campus_and_unverified(self):
        from cis.views.student import StudentViewSet
        vs = StudentViewSet()
        vs.request = self.factory.get('/ce/api/student')
        vs.request.user = self.user
        vs.format_kwarg = None
        qs = vs.get_queryset()
        self.assertIn(self.stu_a, qs)
        self.assertIn(self.stu_unverified, qs)
        self.assertNotIn(self.stu_b, qs)

    # 2. detail view ----------------------------------------------------------
    def test_detail_out_of_scope_403(self):
        resp = self.client.get(reverse('cis:student', args=[self.stu_b.id]))
        self.assertEqual(resp.status_code, 403)

    def test_detail_in_scope_200(self):
        resp = self.client.get(reverse('cis:student', args=[self.stu_a.id]))
        self.assertEqual(resp.status_code, 200)

    def test_detail_unverified_200(self):
        resp = self.client.get(reverse('cis:student', args=[self.stu_unverified.id]))
        self.assertEqual(resp.status_code, 200)

    # 3. delete_record --------------------------------------------------------
    def test_delete_out_of_scope_403_and_record_survives(self):
        resp = self.client.get(reverse('cis:student_delete', args=[self.stu_b.id]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Student.objects.filter(pk=self.stu_b.id).exists())

    # 4. bulk gate ------------------------------------------------------------
    def test_bulk_action_gates_out_of_scope_student(self):
        # bulk_set_status_pending sets application_status='pending' on ids[];
        # chosen for a clean, unambiguous assertion (a plain field write).
        Student.objects.filter(pk__in=[self.stu_a.id, self.stu_b.id]).update(
            application_status='applied')

        # out-of-scope verified student must NOT be modified
        self.client.post(reverse('cis:student_bulk_actions'), {
            'action': 'bulk_set_status_pending',
            'ids[]': [str(self.stu_b.id)],
        })
        self.stu_b.refresh_from_db()
        self.assertEqual(self.stu_b.application_status, 'applied')

        # in-scope verified student DOES get updated
        self.client.post(reverse('cis:student_bulk_actions'), {
            'action': 'bulk_set_status_pending',
            'ids[]': [str(self.stu_a.id)],
        })
        self.stu_a.refresh_from_db()
        self.assertEqual(self.stu_a.application_status, 'pending')

    # 5. index dropdown -------------------------------------------------------
    def test_index_dropdown_lists_only_accessible_campus(self):
        resp = self.client.get(reverse('cis:students'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('name="campus"', html)
        self.assertIn(self.campus_a.name, html)
        self.assertNotIn(self.campus_b.name, html)

    # 6. lazy-tab endpoint (detail data loads through here) -------------------
    def test_tab_out_of_scope_403(self):
        # The detail page loads its real data via /student/<uuid>/tab/<slug>/;
        # it must be object-gated too, else it's an IDOR read bypass.
        resp = self.client.get(
            reverse('cis:student_tab', args=[self.stu_b.id, 'details']))
        self.assertEqual(resp.status_code, 403)

    def test_tab_in_scope_ok(self):
        resp = self.client.get(
            reverse('cis:student_tab', args=[self.stu_a.id, 'details']))
        self.assertEqual(resp.status_code, 200)

    # 7. PDF download endpoint -----------------------------------------------
    def test_pdf_out_of_scope_403(self):
        # Guard fires before record.as_pdf(), so no PDF toolchain is invoked.
        resp = self.client.get(reverse('cis:student_pdf', args=[self.stu_b.id]))
        self.assertEqual(resp.status_code, 403)

    # 8. delete_recommendation must NOT be emptied by the student-id gate -----
    def test_delete_recommendation_excluded_from_student_gate(self):
        from cis.models.student import StudentRecommendation
        rec = StudentRecommendation.objects.create(
            student=self.stu_a, term=self.term, submitted_by=self.user,
            recommendation={})
        self.client.post(reverse('cis:student_bulk_actions'), {
            'action': 'delete_recommendation',
            'ids[]': [str(rec.id)],
        })
        # If the central gate had filtered these StudentRecommendation ids
        # against Student, ids[] would be emptied and the row would survive.
        self.assertFalse(StudentRecommendation.objects.filter(pk=rec.id).exists())

    def test_delete_recommendation_gated_by_student_campus(self):
        # A recommendation of an out-of-scope verified student must NOT be
        # deletable via a crafted bulk POST.
        from cis.models.student import StudentRecommendation
        rec = StudentRecommendation.objects.create(
            student=self.stu_b, term=self.term, submitted_by=self.user,
            recommendation={})
        self.client.post(reverse('cis:student_bulk_actions'), {
            'action': 'delete_recommendation',
            'ids[]': [str(rec.id)],
        })
        self.assertTrue(StudentRecommendation.objects.filter(pk=rec.id).exists())

    # 9. register_for_class ---------------------------------------------------
    def test_register_for_class_out_of_scope_403(self):
        resp = self.client.get(
            reverse('cis:register_for_class', args=[self.stu_b.id]))
        self.assertEqual(resp.status_code, 403)

    def test_register_for_class_in_scope_not_403(self):
        resp = self.client.get(
            reverse('cis:register_for_class', args=[self.stu_a.id]))
        self.assertNotEqual(resp.status_code, 403)

    # 10. student_profile_changes ---------------------------------------------
    def test_student_profile_changes_out_of_scope_403(self):
        resp = self.client.get(
            reverse('cis:student_profile_changes', args=[self.stu_b.id]))
        self.assertEqual(resp.status_code, 403)

    # 11. delete_faa ----------------------------------------------------------
    def test_delete_faa_out_of_scope_403_and_row_survives(self):
        from cis.models.student import StudentTuitionAssistance
        faa = StudentTuitionAssistance.objects.create(
            student=self.stu_b, term=self.term, status='Not Yet Submitted')
        resp = self.client.get(
            reverse('cis:delete_faa_request', args=[faa.id]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(StudentTuitionAssistance.objects.filter(pk=faa.id).exists())

    # 12. delete_support_doc --------------------------------------------------
    def test_delete_support_doc_out_of_scope_403_and_row_survives(self):
        from cis.models.student import StudentSupportingDocument
        # media is a FileField; we pass a string path — the DB stores it without
        # fetching the actual file, so no S3 call is made in tests.
        doc = StudentSupportingDocument.objects.create(
            student=self.stu_b, term=self.term, media='test/fake_doc.pdf')
        resp = self.client.get(
            reverse('cis:delete_support_doc', args=[doc.id]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(StudentSupportingDocument.objects.filter(pk=doc.id).exists())

    # 13. get_payment_link via student_ajax -----------------------------------
    def test_get_payment_link_out_of_scope_403(self):
        # Gate fires before the term lookup, so no term param needed.
        resp = self.client.get(
            reverse('cis:student_ajax') + f'?action=get_payment_link&id={self.stu_b.id}')
        self.assertEqual(resp.status_code, 403)
