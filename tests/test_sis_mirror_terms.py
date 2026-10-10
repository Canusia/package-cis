"""SIS mirror term selection: the registration-status-email setting's
`sis_mirror_terms` limits which registrations the scheduled mirror (and the
Pending SIS Mirror tab, which shares pending_sis_mirror()) picks up.
Nothing ticked = every term. A ticked parent term includes its sub-terms.
"""
import importlib.util
import json
import uuid
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import RequestFactory, TestCase

from cis.models import CustomUser
from cis.models.course import Cohort, Course
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import Student
from cis.models.term import AcademicYear, Term
from cis.settings.registration_status_email import registration_status_email

ETHOS_PATH = ('ethos.ethos.library.ethos.Ethos' if importlib.util.find_spec('ethos.ethos')
              else 'ethos.library.ethos.Ethos')


class SisMirrorTermsTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.create_user(username='cron', email='cron@example.com', password='x')
        self.cohort = Cohort.objects.create(name='Astronomy', designator='A')
        ay = AcademicYear.objects.create(name='2026-2027')
        self.fall = Term.objects.create(label='Fall 2026', code='26FA', academic_year=ay)
        self.fall_a = Term.objects.create(label='Fall 2026 A', code='26FAA', academic_year=ay,
                                          parent=self.fall)
        self.fall_b = Term.objects.create(label='Fall 2026 B', code='26FAB', academic_year=ay,
                                          parent=self.fall)
        self.spring = Term.objects.create(label='Spring 2027', code='27SP', academic_year=ay)
        self.reg = {t.code: self._registration(t) for t in
                    (self.fall, self.fall_a, self.fall_b, self.spring)}

    def _registration(self, term):
        short = uuid.uuid4().hex[:8]
        course = Course.objects.create(catalog_number='001', title='Astronomy',
                                       name=f'A {short}', cohort=self.cohort)
        section = ClassSection.objects.create(
            course=course, term=term, class_number=f'A-{short}', section_number='01',
            external_sis_id=uuid.uuid4(), meta={})
        student = Student.objects.create(
            user=CustomUser.objects.create_user(
                username=f'stu-{short}', email=f'{short}@example.com', password='x',
                first_name='S', last_name=short),
            sis_id=uuid.uuid4())
        reg = StudentRegistration.objects.create(
            student=student, class_section=section, status='registered', status_changed_on={})
        StudentRegistration.objects.filter(pk=reg.pk).update(needs_mirroring=True)
        return reg

    def _configure(self, terms):
        Setting.objects.update_or_create(
            key=registration_status_email.key,
            defaults={'value': {'sis_mirror_trigger': ['registered'],
                                'sis_mirror_terms': [str(t.id) for t in terms]}})

    def _pending_codes(self):
        return sorted(r.class_section.term.code for r in
                      StudentRegistration.objects.pending_sis_mirror())

    def test_nothing_ticked_means_every_term(self):
        self._configure([])
        self.assertEqual(self._pending_codes(), ['26FA', '26FAA', '26FAB', '27SP'])

    def test_setting_saved_before_this_field_existed_means_every_term(self):
        Setting.objects.update_or_create(
            key=registration_status_email.key,
            defaults={'value': {'sis_mirror_trigger': ['registered']}})
        self.assertEqual(self._pending_codes(), ['26FA', '26FAA', '26FAB', '27SP'])

    def test_one_term_ticked(self):
        self._configure([self.spring])
        self.assertEqual(self._pending_codes(), ['27SP'])

    def test_parent_term_includes_its_sub_terms(self):
        self._configure([self.fall])
        self.assertEqual(self._pending_codes(), ['26FA', '26FAA', '26FAB'])

    def test_sub_term_alone_excludes_parent_and_siblings(self):
        self._configure([self.fall_a])
        self.assertEqual(self._pending_codes(), ['26FAA'])

    def test_unticked_terms_stay_queued(self):
        self._configure([self.spring])
        list(StudentRegistration.objects.pending_sis_mirror())
        self.assertTrue(StudentRegistration.objects.get(pk=self.reg['26FA'].pk).needs_mirroring)

    def test_explicit_term_ids_override_the_setting(self):
        self._configure([self.spring])
        qs = StudentRegistration.objects.pending_sis_mirror(['registered'], term_ids=[])
        self.assertEqual(qs.count(), 4)

    def test_with_descendants(self):
        self.assertEqual(
            set(Term.with_descendants([self.fall.id])), {self.fall, self.fall_a, self.fall_b})
        self.assertEqual(set(Term.with_descendants([])), set())

    def test_form_lists_terms_and_saves_ids_as_strings(self):
        request = RequestFactory().get('/')
        form = registration_status_email(request)
        field = form.fields['sis_mirror_terms']
        values = [v for v, _ in field.choices]
        self.assertEqual(set(values), {str(t.id) for t in
                                       (self.fall, self.fall_a, self.fall_b, self.spring)})
        cleaned = field.clean([str(self.fall.id), str(self.spring.id)])
        self.assertEqual(sorted(cleaned), sorted([str(self.fall.id), str(self.spring.id)]))
        json.dumps(cleaned)   # _to_python stores cleaned_data as JSON
        self.assertFalse(field.required)
        sub_labels = [label for v, label in field.choices if v == str(self.fall_a.id)]
        self.assertTrue(sub_labels[0].startswith('— '))

    @patch(ETHOS_PATH)
    def test_cron_sends_only_ticked_terms(self, MockEthos):
        self._configure([self.spring])
        try:
            from ethos.ethos.models import EthosLog
        except ImportError:
            from ethos.models import EthosLog
        client = MockEthos.return_value
        client.mirror_registration.side_effect = lambda *a, **k: (False, EthosLog.objects.create(
            method='POST', url='https://example.invalid/api/section-registrations',
            message_type='class_registered', request_body={}, response_status=400,
            response_body='{"errors":[{"message":"test"}]}'))
        call_command('send_registrations_to_sis')
        sent_sections = {call.args[1] for call in client.mirror_registration.call_args_list}
        self.assertEqual(sent_sections, {str(self.reg['27SP'].class_section.sis_id)})
