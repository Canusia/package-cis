"""FERPA consent per campus (package-cis#65).

Spec: docs/superpowers/specs/2026-10-08-ferpa-per-campus-design.md
"""
import uuid

from django.conf import settings
from django.test import TestCase, override_settings

from cis.models import CustomUser
from cis.models.course import Campus
from cis.models.settings import Setting
from cis.models.student import Student, StudentFerpa
from cis.models.term import AcademicYear, Term

REG_KEY = f'{settings.CAMPUS_CODE_PREFIX}_cis_registrations'


class FerpaFixtureMixin:
    """ewu = the deployment campus (single-campus tests); a/b = two more
    prefixed campuses, named to sort after it, for multi-campus tests."""

    def build(self):
        from django.contrib.auth.models import Group
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        prefix = settings.CAMPUS_CODE_PREFIX
        self.ewu = Campus.objects.filter(code__startswith=prefix).order_by('name').first() \
            or Campus.objects.create(name='AAA Deployment', code=prefix)
        sfx = uuid.uuid4().hex[:6]
        self.a = Campus.objects.create(name=f'zz College A {sfx}', code=f'{prefix}_A{sfx}')
        self.b = Campus.objects.create(name=f'zz College B {sfx}', code=f'{prefix}_B{sfx}')
        user = CustomUser.objects.create_user(
            username=f'stu{sfx}', email=f'stu{sfx}@example.com', password='x')
        self.student = Student.objects.create(user=user)

    def term(self, campus, code):
        from contextlib import nullcontext
        from cis.campus_context import campus_context
        with (campus_context(campus) if campus is not None else nullcontext()):
            year = AcademicYear.objects.create(name=f'AY-{uuid.uuid4().hex[:6]}', campus=campus)
            return Term.objects.create(academic_year=year, code=code, label=code)

    def open_terms(self, campus, *terms):
        Setting.objects.update_or_create(
            key=REG_KEY, campus=campus,
            defaults={'value': {'registration_terms': [str(t.id) for t in terms],
                                'active_term': str(terms[0].id)}})


import datetime  # noqa: E402
from unittest import mock  # noqa: E402

from cis.campus_context import campus_context  # noqa: E402
from cis import ferpa as F  # noqa: E402


class SingleCampusFerpaTests(FerpaFixtureMixin, TestCase):
    def setUp(self):
        self.build()
        self.t = self.term(None, '202610')
        self.open_terms(None, self.t)

    def _sign(self, campus, codes):
        rec = StudentFerpa.objects.create(student=self.student, campus=campus,
                                          permissions_granted={})
        F.record_ferpa_completion(rec, codes)
        return rec

    def test_no_record_is_not_current(self):
        self.assertFalse(F.ferpa_is_current(self.student))

    def test_current_for_the_deployment_campus(self):
        self._sign(self.ewu, ['202610'])
        self.assertTrue(F.ferpa_is_current(self.student))
        self.assertEqual(F.ferpa_record(self.student), StudentFerpa.objects.get(student=self.student))

    def test_stale_terms_are_not_current(self):
        self._sign(self.ewu, ['202530'])
        self.assertFalse(F.ferpa_is_current(self.student))

    def test_no_open_terms_is_not_current(self):
        self._sign(self.ewu, [])
        Setting.objects.filter(key=REG_KEY).delete()
        self.assertFalse(F.ferpa_is_current(self.student))

    def test_order_of_codes_does_not_matter(self):
        t2 = self.term(None, '202620')
        self.open_terms(None, self.t, t2)
        self._sign(self.ewu, ['202620', '202610'])
        self.assertTrue(F.ferpa_is_current(self.student))

    def test_record_completion_mirrors_meta(self):
        self._sign(self.ewu, ['202610'])
        self.student.refresh_from_db()
        self.assertEqual(self.student.meta['ferpa_completed_for'], ['202610'])
        self.assertEqual(self.student.meta['ferpa_completed_on'],
                         datetime.date.today().strftime('%m/%d/%Y'))

    def test_meta_alone_no_longer_counts(self):
        type(self.student).objects.filter(pk=self.student.pk).update(
            meta={'ferpa_completed_for': ['202610']})
        self.student.refresh_from_db()
        self.assertFalse(F.ferpa_is_current(self.student))

    def test_done_for_term(self):
        self._sign(self.ewu, ['202610'])
        self.assertTrue(F.ferpa_done_for_term(self.student, self.t))
        self.assertFalse(F.ferpa_done_for_term(self.student, None))

    def test_model_shims(self):
        self.assertFalse(StudentFerpa.has_signed(self.student))
        self.assertFalse(self.student.get_ferpa())
        rec = self._sign(self.ewu, ['202610'])
        self.assertTrue(StudentFerpa.has_signed(self.student))
        self.assertEqual(self.student.get_ferpa(), rec)
        self.assertEqual(self.student.ferpa_completed_for, ['202610'])
        self.assertEqual(self.student.ferpa_completed_on,
                         datetime.date.today().strftime('%m/%d/%Y'))


@override_settings(MULTI_CAMPUS=True)
class MultiCampusFerpaTests(FerpaFixtureMixin, TestCase):
    def setUp(self):
        self.build()
        self.ta = self.term(self.a, '202610')
        self.tb = self.term(self.b, '202610')   # shared code
        self.open_terms(self.a, self.ta)
        self.open_terms(self.b, self.tb)

    def _rec(self, campus, codes):
        return StudentFerpa.objects.create(student=self.student, campus=campus,
                                           permissions_granted={}, completed_for=codes)

    def test_consent_on_a_does_not_satisfy_b(self):
        self._rec(self.a, ['202610'])
        with campus_context(self.a):
            self.assertTrue(F.ferpa_is_current(self.student))
        with campus_context(self.b):
            self.assertFalse(F.ferpa_is_current(self.student))
            self.assertIsNone(F.ferpa_record(self.student))

    def test_null_campus_row_never_counts(self):
        self._rec(None, ['202610'])
        with campus_context(self.a):
            self.assertFalse(F.ferpa_is_current(self.student))

    def test_no_campus_context_is_not_current_and_does_not_raise(self):
        self._rec(self.a, ['202610'])
        self.assertFalse(F.ferpa_is_current(self.student))
        self.assertIsNone(F.ferpa_record(self.student))

    def test_done_for_term_uses_the_terms_campus(self):
        self._rec(self.a, ['202610'])
        self.assertTrue(F.ferpa_done_for_term(self.student, self.ta))
        self.assertFalse(F.ferpa_done_for_term(self.student, self.tb))


class FormHookTests(FerpaFixtureMixin, TestCase):
    def setUp(self):
        self.build()

    def test_default_form_class(self):
        from cis.services.tenant_services import get_tenant_service
        self.assertIs(F.ferpa_form_class(self.ewu),
                      get_tenant_service('ferpa_form').StudentFerpaForm)

    def test_tenant_hook_wins_per_campus(self):
        class AForm:
            pass

        class BForm:
            pass

        def hook(campus):
            return AForm if campus == self.a else BForm
        with mock.patch('cis.ferpa.get_tenant_override', return_value=hook):
            self.assertIs(F.ferpa_form_class(self.a), AForm)
            self.assertIs(F.ferpa_form_class(self.b), BForm)

    def test_template_passes_campus_only_when_accepted(self):
        svc = mock.Mock()
        svc.form_template = lambda: 'old.html'
        with mock.patch('cis.ferpa.get_tenant_service', return_value=svc):
            self.assertEqual(F.ferpa_form_template(self.a), 'old.html')
        svc.form_template = lambda campus=None: f'{campus.code}.html'
        with mock.patch('cis.ferpa.get_tenant_service', return_value=svc):
            self.assertEqual(F.ferpa_form_template(self.a), f'{self.a.code}.html')


from django.test import RequestFactory  # noqa: E402


class CeTabTests(FerpaFixtureMixin, TestCase):
    def setUp(self):
        self.build()
        sfx = uuid.uuid4().hex[:6]
        self.staff = CustomUser.objects.create_superuser(
            username=f'ce{sfx}', email=f'ce{sfx}@x.com', password='x')

    def _ctx(self, user):
        from cis.tabs.student import ferpa_tab
        request = RequestFactory().get('/')
        request.user = user
        return ferpa_tab(request, self.student)

    def test_single_campus_context_unchanged(self):
        rec = StudentFerpa.objects.create(student=self.student, campus=self.ewu,
                                          permissions_granted={})
        ctx = self._ctx(self.staff)
        self.assertEqual(ctx['ferpa'], rec)
        self.assertNotIn('ferpa_by_campus', ctx)

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_lists_each_accessible_campus(self):
        rec = StudentFerpa.objects.create(student=self.student, campus=self.a,
                                          permissions_granted={})
        rows = dict(self._ctx(self.staff)['ferpa_by_campus'])
        self.assertEqual(rows[self.a], rec)
        self.assertIsNone(rows[self.b])

    @override_settings(MULTI_CAMPUS=True)
    def test_ce_user_sees_only_their_campus(self):
        with mock.patch('cis.tabs.student.get_accessible_campuses',
                        return_value=Campus.objects.filter(pk=self.a.pk)):
            rows = dict(self._ctx(self.staff)['ferpa_by_campus'])
        self.assertEqual(list(rows), [self.a])

    @override_settings(MULTI_CAMPUS=True)
    def test_signatures_tab_uses_the_registration_campus(self):
        from cis.tabs.registration import signatures_tab
        rec_b = StudentFerpa.objects.create(student=self.student, campus=self.b,
                                            permissions_granted={})
        registration = mock.Mock()
        registration.student = self.student
        registration.class_section.course.campus = self.b
        registration.get_student_signature.return_value = None
        self.assertEqual(signatures_tab(None, registration)['ferpa'], rec_b)


class ImportCommandTests(FerpaFixtureMixin, TestCase):
    def setUp(self):
        self.build()

    def test_import_requires_campus_on_multi_campus(self):
        from django.core.management import CommandError, call_command
        with override_settings(MULTI_CAMPUS=True), self.assertRaises(CommandError):
            call_command('import_student_ferpa', path='/nonexistent.csv')

    def test_import_creates_per_campus_and_is_idempotent(self):
        import os
        import tempfile
        from django.core.management import call_command
        type(self.student).objects.filter(pk=self.student.pk).update(pidm='123')
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as f:
            f.write('studentid,name1,code1,name2,code2,name3,code3,name4,code4\n'
                    '123,Pat,P,,,,,,\n')
        try:
            call_command('import_student_ferpa', path=f.name, campus=self.a.code)
            call_command('import_student_ferpa', path=f.name, campus=self.a.code)
        finally:
            os.unlink(f.name)
        rows = StudentFerpa.objects.filter(student=self.student)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().campus, self.a)
        self.assertEqual(rows.get().legacy_campus, [])


class SingleCampusIgnoresDataCampusTests(FerpaFixtureMixin, TestCase):
    """Review fix: on single-campus every record is the deployment campus's, so
    a course or academic year pointing at another campus must not hide it."""

    def setUp(self):
        self.build()
        self.rec = StudentFerpa.objects.create(
            student=self.student, campus=self.ewu, permissions_granted={},
            completed_for=['202610'])

    def test_explicit_other_campus_still_finds_the_record(self):
        self.assertEqual(F.ferpa_record(self.student, self.a), self.rec)

    def test_done_for_a_term_whose_year_names_another_campus(self):
        term = self.term(self.a, '202610')
        self.assertTrue(F.ferpa_done_for_term(self.student, term))

    def test_signatures_tab_with_a_course_on_another_campus(self):
        from cis.tabs.registration import signatures_tab
        registration = mock.Mock()
        registration.student = self.student
        registration.class_section.course.campus = self.a
        registration.get_student_signature.return_value = None
        self.assertEqual(signatures_tab(None, registration)['ferpa'], self.rec)
