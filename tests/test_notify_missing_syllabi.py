"""package-cis#117: missing-syllabus reminders skip cancelled sections, go out
once per instructor per term (so {{term}} matches the sections listed), and
still go out on the end date."""
from datetime import date
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from cis.management.commands.notify_missing_syllabi import (
    CANCELLED_STATUSES, sections_missing_syllabi
)
from cis.models.section import ClassSection, ClassSectionSyllabi
from cis.models.term import Term
from cis.tests.test_syllabi_review_settings import (
    NOTIFY_SEND, SyllabiFixtureMixin, saved_form_value, set_value
)


class NotifyMissingSyllabiTests(SyllabiFixtureMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.make_world()
        cls.other_term = Term.objects.create(
            academic_year=cls.term.academic_year,
            code=f'{cls.term.code}Y', label=f'Yearlong {cls.term.code}')

    def setUp(self):
        set_value(saved_form_value(
            term=[str(self.term.id)],
            missing_syllabus_email_message='{{term}}|{{section_list}}'))

    def add_section(self, term, number, status='A'):
        return ClassSection.objects.create(
            course=self.course, term=term, class_number=number,
            section_number='01', teacher=self.teacher, status=status)

    def line(self, *sections):
        return f'{sections[0].term}|' + ', '.join(
            f'{s.course.name}/{s.class_number}/01' for s in sections)

    def sent(self):
        """Run the job; [(to, text_body)] of the missing-syllabus emails."""
        with mock.patch(NOTIFY_SEND) as send:
            call_command('notify_missing_syllabi')
        return [(list(c.args[4]), c.args[1]) for c in send.call_args_list
                if c.args[0] == 'MISSING']

    def test_cancelled_status_is_the_models_cancelled_choice(self):
        cancelled = [code for code, label in ClassSection.CLASS_STATUS
                     if label == 'Cancelled']
        self.assertTrue(cancelled)
        self.assertTrue(set(cancelled) <= set(CANCELLED_STATUSES))

    def test_only_sections_without_upload_are_missing(self):
        uploaded = self.add_section(self.term, 'U1')
        ClassSectionSyllabi.objects.create(media='s.pdf').class_sections.add(
            uploaded)
        missing = sections_missing_syllabi([str(self.term.id)])
        self.assertEqual(list(missing), [self.section])

    def test_cancelled_sections_are_not_missing(self):
        self.add_section(self.term, 'X1', status='C')
        missing = sections_missing_syllabi([str(self.term.id)])
        self.assertEqual(list(missing), [self.section])

    def test_instructor_with_only_cancelled_sections_gets_no_email(self):
        ClassSection.objects.filter(id=self.section.id).update(status='C')
        self.assertEqual(self.sent(), [])

    def test_email_is_per_term_and_lists_each_section_once(self):
        """Same class number active in one term and cancelled in another was
        listed twice in one email labelled with only one term."""
        set_value(saved_form_value(
            term=[str(self.term.id), str(self.other_term.id)],
            missing_syllabus_email_message='{{term}}|{{section_list}}'))
        self.add_section(self.other_term, self.section.class_number, status='C')
        yearlong = self.add_section(self.other_term, 'Y2')

        bodies = sorted(body for _to, body in self.sent())

        self.assertEqual(
            bodies, sorted([self.line(self.section), self.line(yearlong)]))

    def test_runs_on_the_end_date(self):
        today = date.today().strftime('%m/%d/%Y')
        set_value(saved_form_value(
            term=[str(self.term.id)], starting_date=today, ending_date=today,
            missing_syllabus_email_message='{{term}}|{{section_list}}'))
        self.assertEqual(
            [body for _to, body in self.sent()], [self.line(self.section)])

    def test_not_run_after_the_end_date(self):
        set_value(saved_form_value(
            term=[str(self.term.id)],
            starting_date='01/01/2000', ending_date='01/02/2000'))
        self.assertEqual(self.sent(), [])
