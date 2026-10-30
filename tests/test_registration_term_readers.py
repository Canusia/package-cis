"""Reminders and recommendation coverage read the section's own term tree.

`ClassSection.registration_term` is being retired: a section has one `term`, and
that term's `parent` stands in for the registration term. On a tenant whose
registration-terms setting lists sub-terms [A, B] while the sections on those
sub-terms carry registration_term=P (the pre_save default), the old
`registration_term__in=` filters matched nothing.
"""
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.http import QueryDict
from django.test import TestCase

from cis.models.course import Course, Cohort
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student, StudentRecommendation
from cis.models.term import AcademicYear, Term


class RegistrationTermReaderBase(TestCase):
    def setUp(self):
        # Test the cis defaults, not a tenant override.
        override = patch(
            'cis.models.section._tenant_registration_override', return_value=None)
        override.start()
        self.addCleanup(override.stop)

        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@localhost'})
        ay = AcademicYear.objects.create(name='2025-2026')
        self.parent = Term.objects.create(label='AY 25', code='AY25', academic_year=ay)
        self.a = Term.objects.create(
            label='Fall A', code='FAA', academic_year=ay, parent=self.parent)
        self.b = Term.objects.create(
            label='Fall B', code='FAB', academic_year=ay, parent=self.parent)
        self.hs = HighSchool.objects.create(name='Lincoln High', status='Active')
        cohort = Cohort.objects.create(name='English', designator='ENGL')
        course = Course.objects.create(
            name='ENGL& 101', title='Comp I', catalog_number='101', cohort=cohort,
            status='Active', registration_eligibility=['JR*'])
        # registration_term is left to the pre_save default: the parent.
        self.section = ClassSection.objects.create(
            course=course, term=self.a, highschool=self.hs,
            class_number='C00001', section_number='01')
        self.assertEqual(self.section.registration_term_id, self.parent.id)
        user = CustomUser.objects.create(username='s1', email='s1@x.com')
        self.student = Student.objects.create(
            user=user, highschool=self.hs, grade_level='JR')
        self.registration = StudentRegistration.objects.create(
            student=self.student, class_section=self.section, highschool=self.hs,
            status='applied', status_changed_on={})


class CounselorReminderTests(RegistrationTermReaderBase):
    def test_counselor_reminder_selects_sub_term_class(self):
        found = StudentRegistration.objects.awaiting_recommendation(
            terms=[self.a, self.b])
        self.assertIn(self.registration.id, [r.id for r in found])

    def test_counselor_reminder_selects_parent_setting(self):
        found = StudentRegistration.objects.awaiting_recommendation(
            terms=[self.parent])
        self.assertIn(self.registration.id, [r.id for r in found])

    def test_other_term_is_not_selected(self):
        other = Term.objects.create(
            label='Spring', code='SP26', academic_year=self.a.academic_year)
        found = StudentRegistration.objects.awaiting_recommendation(terms=[other])
        self.assertEqual(list(found), [])


class MissingPaymentReminderTests(RegistrationTermReaderBase):
    def _run(self, terms):
        Student.objects.filter(pk=self.student.pk).update(current_student_balance=50)
        sent = []
        self.sent_term_ids = []
        with patch('cis.utils.is_student_billpay_open', return_value=True), \
                patch('cis.utils.registration_terms', return_value=terms), \
                patch('cis.utils.active_term', return_value=self.a), \
                patch.object(Student, 'send_payment_url',
                             lambda s, term_id, mode: (sent.append(s.pk),
                                                       self.sent_term_ids.append(term_id))), \
                patch.object(Student, 'add_note', lambda *a, **k: None):
            call_command('send_missing_payment_reminder', stdout=StringIO())
        return sent

    def test_missing_payment_reminder_finds_student(self):
        self.assertEqual(self._run(Term.objects.filter(pk__in=[self.a.pk, self.b.pk])),
                         [self.student.pk])

    def test_no_registration_terms_configured(self):
        self.assertEqual(self._run(None), [])

    def test_missing_payment_reminder_links_billing_term(self):
        # Active term is sub-term A, which bills with its parent: the emailed
        # link must carry the parent's id, where the charges sit.
        self._run(Term.objects.filter(pk__in=[self.a.pk, self.b.pk]))
        self.assertEqual(self.sent_term_ids, [self.parent.id])


class RecommendationCoverageTests(RegistrationTermReaderBase):
    def _rec(self, term):
        return StudentRecommendation.objects.create(
            student=self.student, term=term, recommendation={})

    def _both_ways(self):
        from cis.views.eager import annotate_registration_flags
        regs = StudentRegistration.objects.filter(pk=self.registration.pk)
        fresh = StudentRegistration.objects.get(pk=self.registration.pk)
        annotated = [r._has_recommendation for r in annotate_registration_flags(regs)]
        return fresh.has_recommendation(), annotated

    def test_no_recommendation_is_false(self):
        self.assertEqual(self._both_ways(), (False, [False]))

    def test_rec_on_parent_covers_sub_term_registration(self):
        self._rec(self.parent)
        self.assertEqual(self._both_ways(), (True, [True]))

    def test_rec_on_sub_term_covers_registration(self):
        self._rec(self.a)
        self.assertEqual(self._both_ways(), (True, [True]))

    def test_rec_on_sibling_sub_term_does_not_cover(self):
        self._rec(self.b)
        self.assertEqual(self._both_ways(), (False, [False]))


class SectionTermTreeFilterTests(RegistrationTermReaderBase):
    """Request parameters keep their `registration_term_*` names but now mean
    "the section's term, or anything under it"."""

    def setUp(self):
        super().setUp()
        # The stored registration_term must not matter: point it at a term
        # unrelated to the section's tree, as an old import could have left it.
        unrelated = Term.objects.create(
            label='Unrelated', code='ZZ01', academic_year=self.a.academic_year)
        ClassSection.objects.filter(pk=self.section.pk).update(
            registration_term=unrelated)

    def _admin(self):
        admin = CustomUser.objects.create_superuser(
            username='su3', email='su3@x.com', password='x')
        admin.groups.add(Group.objects.get_or_create(name='ce')[0])
        return admin

    def _viewset(self, cls, **params):
        from rest_framework.test import APIRequestFactory
        request = APIRequestFactory().get('/x', params)
        request.user = self._admin()
        viewset = cls()
        viewset.request = request
        viewset.format_kwarg = None
        return viewset

    def test_missing_recommendation_filter_uses_term_tree(self):
        from cis.views.student import StudentViewSet
        viewset = self._viewset(
            StudentViewSet, record_type='missing_recommendation',
            registration_term_id=str(self.parent.id))
        self.assertTrue(
            viewset.get_queryset().filter(pk=self.student.pk).exists())

    def test_missing_recommendation_filter_ignores_unrelated_term(self):
        from cis.views.student import StudentViewSet
        other = Term.objects.create(
            label='Spring', code='SP26', academic_year=self.a.academic_year)
        viewset = self._viewset(
            StudentViewSet, record_type='missing_recommendation',
            registration_term_id=str(other.id))
        self.assertFalse(
            viewset.get_queryset().filter(pk=self.student.pk).exists())

    def test_registrations_filter_by_code_uses_term_tree(self):
        from cis.views.registration import RegistrationViewSet
        viewset = self._viewset(
            RegistrationViewSet, registration_term_code=self.parent.code)
        self.assertIn(
            self.registration.pk, [r.pk for r in viewset.get_queryset()])

    def test_registrations_filter_by_code_excludes_unrelated_term(self):
        from cis.views.registration import RegistrationViewSet
        viewset = self._viewset(
            RegistrationViewSet, registration_term_code=self.b.code)
        self.assertNotIn(
            self.registration.pk, [r.pk for r in viewset.get_queryset()])

    def test_students_by_date_term_tree(self):
        import datetime
        from types import SimpleNamespace
        from cis.reports import students_by_date as module

        saved = {}

        class FakeStorage:
            def save(self, path, content):
                saved['csv'] = content.read().decode('utf-8')
                return path

            def url(self, path):
                return path

        report = module.students_by_date()
        data = {
            'applied_on': ['01/01/2000'],
            'applied_until': [(datetime.date.today()
                               + datetime.timedelta(days=2)).strftime('%m/%d/%Y')],
            'term': [str(self.parent.id)],
            'campus': [],
        }
        task = SimpleNamespace(id='t1', created_by=self._admin())
        with patch.object(module, 'PrivateMediaStorage', FakeStorage), \
                patch.object(module, 'scope_report_by_campus',
                             lambda records, *a, **k: records):
            report.run(task, data)
        lines = saved['csv'].strip().splitlines()
        self.assertTrue(lines[0].endswith('Applied For Class'))
        self.assertTrue(lines[1].endswith('Yes'), lines[1])


class SectionApiDeprecationTests(RegistrationTermReaderBase):
    def _post(self, **extra):
        from rest_framework.test import APIClient
        admin = CustomUser.objects.create_superuser(
            username='su4', email='su4@x.com', password='x')
        admin.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.hs.code = '123456'
        self.hs.save()
        course = self.section.course
        from cis.models.teacher import Teacher
        teacher_user = CustomUser.objects.create(
            username='t1', email='t1@school.edu')
        teacher_user.groups.add(Group.objects.get_or_create(name='instructor')[0])
        Teacher.objects.create(user=teacher_user)
        client = APIClient()
        client.force_authenticate(admin)
        payload = {
            'term_code': self.a.code, 'reference_number': 1, 'teacher_hs_email': 't1@school.edu',
            'highschool_course_name': 'English',
            'section_number': '01', 'start_date': '2025-09-01',
            'end_date': '2025-12-01', 'tuition': 10, 'course_name': course.name,
            'course_title': 'Comp I', 'credit_hours': 3,
            'highschool_ceeb': '123456', 'status': 'A',
        }
        payload.update(extra)
        return client.post('/api/v1/class_sections/', payload, format='json')

    def test_section_api_ignores_registration_term_code(self):
        other = Term.objects.create(
            label='Spring', code='SP26', academic_year=self.a.academic_year)
        response = self._post(registration_term_code=other.code)
        self.assertEqual(response.status_code, 201, response.content)
        self.section.refresh_from_db()
        self.assertEqual(self.section.term_id, self.a.id)
        self.assertEqual(self.section.registration_term_id, self.parent.id)
        self.assertEqual(response.json()['warnings'], [
            'registration_term_code is deprecated and ignored; '
            "set the term's parent instead."])
        self.assertEqual(response.json()['registration_term_code'], self.parent.code)

    def test_section_api_accepts_a_post_without_the_field(self):
        response = self._post()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertNotIn('warnings', response.json())


class RemovedActionTests(TestCase):
    def test_change_registration_term_action_removed(self):
        from cis.views import section as section_views
        from cis.forms import section as section_forms
        self.assertFalse(hasattr(section_views, 'change_registration_term'))
        self.assertFalse(hasattr(section_forms, 'BulkRegistrationTermChangeForm'))

    def test_change_registration_term_action_is_not_dispatched(self):
        from rest_framework.test import APIRequestFactory
        from cis.views.section import do_bulk_action
        request = APIRequestFactory().get(
            '/x', {'action': 'change_registration_term'})
        request.user = CustomUser(username='x')
        request.POST = QueryDict('')
        self.assertIn('invalid action', do_bulk_action(request).content.decode())

    def test_profile_setting_no_longer_lists_registration_term(self):
        from cis.settings import class_section_profile
        flat = [c for row in class_section_profile.CLASS_SECTION_DEFAULT_DISPLAY
                for c in row]
        self.assertNotIn('registration_term', flat)


class AuditRegistrationTermsTests(RegistrationTermReaderBase):
    def test_audit_registration_terms_reports_mismatch(self):
        from student_transactions.models import StudentTransaction
        z = Term.objects.create(
            label='Unrelated', code='ZZ99', academic_year=self.a.academic_year)
        ClassSection.objects.filter(pk=self.section.pk).update(registration_term=z)
        StudentTransaction.objects.create(
            student=self.student, term=z, amount=50, label='class_charge',
            meta={'registration': str(self.registration.pk)})

        out = StringIO()
        call_command('audit_registration_terms', stdout=out)
        text = out.getvalue()
        self.assertIn('C00001', text)
        self.assertIn('ZZ99', text)
        self.assertIn('(a)', text)
        self.assertIn('(b)', text)
        self.assertIn(str(self.registration.pk), text)

    def test_audit_lists_sub_term_sections_registered_on_their_own_term(self):
        # Pre-upgrade charges for such a section sit on the sub-term; after
        # the upgrade the sub-term bills with its parent by default.
        ClassSection.objects.filter(pk=self.section.pk).update(registration_term=self.a)
        out = StringIO()
        call_command('audit_registration_terms', stdout=out)
        text = out.getvalue()
        self.assertIn('C00001', text)
        self.assertIn('Bill with parent term', text)
        self.assertIn(self.a.code, text)

    def test_audit_skips_sub_term_that_bills_separately(self):
        ClassSection.objects.filter(pk=self.section.pk).update(registration_term=self.a)
        Term.objects.filter(pk=self.a.pk).update(bills_with_parent=False)
        out = StringIO()
        call_command('audit_registration_terms', stdout=out)
        self.assertNotIn('C00001', out.getvalue())

    def test_audit_is_quiet_when_everything_matches(self):
        out = StringIO()
        call_command('audit_registration_terms', stdout=out)
        self.assertNotIn('C00001', out.getvalue())


class ImporterIgnoresRegistrationTermTests(RegistrationTermReaderBase):
    def _import(self, code):
        from cis.services.importers.class_section_importer import ClassSectionImporter
        rows = [{
            'name': 'Fall A', 'term_code': self.a.code,
            'reference_number': str(1000 + n), 'section_number': '01',
            'course_name': self.section.course.name, 'course_title': 'Comp I',
            'registration_term_code': code,
        } for n in range(2)]
        with self.assertLogs(
                'cis.services.importers.class_section_importer', level='INFO') as logs:
            ClassSectionImporter(use_bulk_operations=False).process_csv(iter(rows))
        return logs.output

    def test_registration_term_code_is_read_without_error_and_never_written(self):
        out = self._import('NOPE99')
        self.assertFalse(Term.objects.filter(code='NOPE99').exists())
        for section in ClassSection.objects.filter(class_number__in=['1000', '1001']):
            self.assertEqual(section.registration_term_id, self.parent.id)
        self.assertEqual(
            len([m for m in out if 'registration_term_code is deprecated' in m]), 1)


class BillingTermSerializationTests(RegistrationTermReaderBase):
    def test_billing_term_serialises_without_extra_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from cis.serializers.class_section import ClassSectionSerializer
        from cis.views.eager import class_section_select_related

        section = ClassSection.objects.select_related(
            *class_section_select_related()).get(pk=self.section.pk)
        with CaptureQueriesContext(connection) as queries:
            data = ClassSectionSerializer(section).data['billing_term']
        self.assertEqual(data['id'], str(self.parent.id))
        self.assertEqual(data['code'], self.parent.code)
        # Only the plan's prefetches (none for terms) may run.
        term_queries = [q['sql'] for q in queries if 'cis_term' in q['sql']
                        or 'cis_academicyear' in q['sql'] or 'cis_campus' in q['sql']]
        self.assertEqual(term_queries, [])
