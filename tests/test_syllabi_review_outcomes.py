"""Syllabus review outcomes (package-cis #124, #127, #128).

- #128: the Class Syllabi - Review settings form validates dates without a 500.
- #124: a review is recorded on the section (date, reviewer, note; an older
  note is replaced), the export report reads it, CE pages show labels, and the
  CE silent GET path and edit-form field are gone.
- #127: the needs-update reminder skips cancelled and teacherless sections and
  goes out once per instructor per term; an upload saves (history) only the
  sections it is added to.
"""
import datetime
from unittest import mock

from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.core.management import call_command
from django.utils import timezone

from cis.forms.section import ClassSectionForm
from cis.management.commands.notify_missing_syllabi import sections_needing_update
from cis.models.section import ClassSection, ClassSectionSyllabi
from cis.reports.teacher_syllabi_status import (
    derive_status, latest_syllabus, teacher_syllabi_status,
)
from cis.serializers.class_section import ClassSectionSerializer
from cis.settings.syllabi_review import syllabi_review
from cis.tests.test_syllabi_review_settings import (
    MODEL_SEND, NOTIFY_SEND, SyllabiFixtureMixin, saved_form_value, set_value,
)


def _today():
    return timezone.localdate().strftime('%m/%d/%Y')


class SettingsDateTests(SyllabiFixtureMixin, TestCase):
    """#128"""

    @classmethod
    def setUpTestData(cls):
        cls.make_world()

    def form(self, **overrides):
        data = saved_form_value(term=[str(self.term.id)], **overrides)
        return syllabi_review(RequestFactory().post('/', data), data=data)

    def test_end_before_start_is_a_form_error(self):
        form = self.form(starting_date='10/20/2026', ending_date='10/01/2026')
        self.assertFalse(form.is_valid())
        self.assertIn('End Date has to be after start date.', form.errors['ending_date'])

    def test_iso_dates_validate_and_store_as_mdy(self):
        form = self.form(starting_date='2026-10-01', ending_date='2026-10-20')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['starting_date'], '10/01/2026')
        self.assertEqual(form.cleaned_data['ending_date'], '10/20/2026')

    def test_empty_start_date_is_a_field_error(self):
        form = self.form(starting_date='')
        self.assertFalse(form.is_valid())
        self.assertIn('starting_date', form.errors)


class ReviewRecordTests(SyllabiFixtureMixin, TestCase):
    """#124: what a review writes on the section."""

    @classmethod
    def setUpTestData(cls):
        cls.make_world()

    def setUp(self):
        set_value(saved_form_value())
        self.section = ClassSection.objects.get(pk=self.section.pk)

    def test_reviewed_replaces_an_older_note_and_records_the_date(self):
        with mock.patch(MODEL_SEND):
            self.section.mark_syllabi_as_needs_update('Fix grading', updated_by=self.reviewer)
            history_before = self.section.history.count()
            self.section.mark_syllabi_as_reviewed(updated_by=self.reviewer)
        self.section.refresh_from_db()
        self.assertEqual(self.section.syllabi_status, 'reviewed')
        record = self.section.syllabi_status_changed_on
        self.assertEqual(record['note'], '')
        self.assertEqual(record['reviewed_on'], _today())
        self.assertEqual(record['reviewed_by'], str(self.reviewer.pk))
        # The Needs Update note stays in history.
        self.assertEqual(self.section.history.count(), history_before + 1)
        self.assertIn('Fix grading', [
            (h.syllabi_status_changed_on or {}).get('note') for h in self.section.history.all()])

    def test_reviewed_note_is_stored(self):
        with mock.patch(MODEL_SEND):
            self.section.mark_syllabi_as_reviewed('Looks good', updated_by=self.reviewer)
        self.section.refresh_from_db()
        self.assertEqual(self.section.syllabi_status_changed_on['note'], 'Looks good')

    def test_no_reviewer_records_without_a_note_row(self):
        # ClassSectionNote.createdby is required; this used to IntegrityError.
        with mock.patch(MODEL_SEND):
            self.section.mark_syllabi_as_reviewed()
        self.section.refresh_from_db()
        self.assertEqual(self.section.syllabi_status, 'reviewed')

    def test_section_without_an_instructor_is_reviewed_without_email(self):
        ClassSection.objects.filter(pk=self.section.pk).update(teacher=None)
        section = ClassSection.objects.get(pk=self.section.pk)
        with mock.patch(MODEL_SEND) as send, self.assertLogs('cis.models.section', 'WARNING'):
            section.mark_syllabi_as_needs_update('Fix', updated_by=self.reviewer)
        send.assert_not_called()
        section.refresh_from_db()
        self.assertEqual(section.syllabi_status, 'needs update')


class ReportTests(SyllabiFixtureMixin, TestCase):
    """#124: the export report reads the section's review status."""

    @classmethod
    def setUpTestData(cls):
        cls.make_world()

    def add(self, number, status='', with_file=True):
        section = ClassSection.objects.create(
            course=self.course, term=self.term, class_number=number,
            section_number='07', teacher=self.teacher)
        if with_file:
            ClassSectionSyllabi.objects.create(media=f'{number}.pdf').class_sections.add(section)
        ClassSection.objects.filter(pk=section.pk).update(syllabi_status=status)
        return ClassSection.objects.get(pk=section.pk)

    def test_each_status(self):
        cases = {
            'reviewed': 'approved', 'needs update': 'needs_update',
            'pending review': 'submitted', '': 'submitted',
        }
        for i, (status, expected) in enumerate(cases.items()):
            with self.subTest(status=status):
                self.assertEqual(derive_status(self.add(f'R{i}', status)), expected)
        self.assertEqual(derive_status(self.add('R9', with_file=False)), 'not_submitted')

    def test_row_has_section_number_and_reviewed_on(self):
        section = self.add('R1', 'reviewed')
        section.syllabi_status_changed_on = {'reviewed_on': '10/24/2026', 'note': ''}
        row = teacher_syllabi_status()._build_row(section, 'approved', latest_syllabus(section))
        columns = teacher_syllabi_status.COLUMNS
        self.assertEqual(row[columns.index('Section')], '07')
        self.assertEqual(row[columns.index('Syllabus Status')], 'Approved')
        self.assertEqual(row[columns.index('Reviewed On')], '10/24/2026')

    def _queries(self):
        sections = ClassSection.objects.filter(term=self.term).prefetch_related(
            'classsectionsyllabi_set').order_by('class_number')
        with CaptureQueriesContext(connection) as ctx:
            for s in sections:
                derive_status(s, latest_syllabus(s))
        return len(ctx)

    def test_query_count_is_flat(self):
        self.add('Q1')
        one = self._queries()
        self.add('Q2')
        self.add('Q3')
        self.assertEqual(self._queries(), one)


class CEPathTests(SyllabiFixtureMixin, TestCase):
    """#124: CE labels; no silent CE review path."""

    @classmethod
    def setUpTestData(cls):
        cls.make_world()

    def test_bulk_get_no_longer_marks_reviewed(self):
        from cis.views.section import do_bulk_action
        request = RequestFactory().get('/', {'action': 'mark_syllabi_as_reviewed',
                                            'id': str(self.section.pk)})
        request.user = self.reviewer
        response = do_bulk_action(request)
        self.assertIn(b'invalid action', response.content)
        self.section.refresh_from_db()
        self.assertNotEqual(self.section.syllabi_status, 'reviewed')

    def test_edit_form_has_no_syllabi_status(self):
        self.assertNotIn('syllabi_status', ClassSectionForm.base_fields)

    def test_feed_sends_the_label(self):
        self.assertIn('syllabi_status_display', ClassSectionSerializer().fields)
        ClassSection.objects.filter(pk=self.section.pk).update(syllabi_status='needs update')
        section = ClassSection.objects.get(pk=self.section.pk)
        field = ClassSectionSerializer().fields['syllabi_status_display']
        self.assertEqual(field.to_representation(field.get_attribute(section)), 'Needs Update')

    def _banner(self, status, record=None):
        from django.template.loader import render_to_string
        ClassSection.objects.filter(pk=self.section.pk).update(
            syllabi_status=status, syllabi_status_changed_on=record or {})
        section = ClassSection.objects.get(pk=self.section.pk)
        return render_to_string('cis/sections/tabs/_syllabi.html', {'record': section})

    def test_tab_banner(self):
        self.assertNotIn('Marked as', self._banner(''))
        self.assertNotIn('Marked as', self._banner('pending review'))
        self.assertIn('Marked as Needs Update on 10/01/2026',
                      self._banner('needs update', {'reviewed_on': '10/01/2026', 'note': 'x'}))
        reviewed = self._banner('reviewed', {'reviewed_on': '10/02/2026', 'note': 'stale'})
        self.assertIn('Marked as Reviewed on 10/02/2026', reviewed)

    def test_admin_lists_class_numbers(self):
        from django.contrib import admin
        syllabus = ClassSectionSyllabi.objects.create(media='a.pdf')
        syllabus.class_sections.add(self.section)
        model_admin = admin.site._registry.get(ClassSectionSyllabi)
        if model_admin is None:
            self.skipTest('ClassSectionSyllabi admin not registered')
        self.assertEqual(model_admin.class_sections(syllabus), str(self.section.class_number))


class NeedsUpdateReminderGroupingTests(SyllabiFixtureMixin, TestCase):
    """#127: the needs-update reminder."""

    @classmethod
    def setUpTestData(cls):
        cls.make_world()

    def setUp(self):
        set_value(saved_form_value(
            term=[str(self.term.id)],
            needs_update_email_message='{{term}}|{{course}}|{{note}}|{{section_list}}'))

    def add(self, number, note, teacher='same', status='A'):
        section = ClassSection.objects.create(
            course=self.course, term=self.term, class_number=number, section_number='01',
            teacher=self.teacher if teacher == 'same' else teacher, status=status)
        ClassSectionSyllabi.objects.create(media=f'{number}.pdf').class_sections.add(section)
        ClassSection.objects.filter(pk=section.pk).update(
            syllabi_status='needs update', syllabi_status_changed_on={'note': note})
        return section

    def reminders(self):
        with mock.patch(NOTIFY_SEND) as send:
            call_command('notify_missing_syllabi')
        return [c.args[1] for c in send.call_args_list if c.args[0] == 'NEEDS UPDATE']

    def test_cancelled_and_teacherless_sections_are_skipped(self):
        live = self.add('N1', 'Fix')
        cancelled = self.add('N2', 'Fix', status='C')
        orphan = self.add('N3', 'Fix', teacher=None)
        found = set(sections_needing_update([str(self.term.id)]))
        self.assertEqual(found, {live})
        self.assertEqual(len(self.reminders()), 1)  # and the run did not crash
        self.assertNotIn(cancelled, found)
        self.assertNotIn(orphan, found)

    def test_one_email_per_instructor_lists_every_note(self):
        self.add('N1', 'Add grading scale')
        self.add('N2', 'Add policy')
        bodies = self.reminders()
        self.assertEqual(len(bodies), 1)
        self.assertIn('Add grading scale', bodies[0])
        self.assertIn('Add policy', bodies[0])
        self.assertIn('/N1/01', bodies[0])
        self.assertIn('/N2/01', bodies[0])


class UploadSignalTests(SyllabiFixtureMixin, TestCase):
    """#127: an upload saves only the sections it is added to."""

    @classmethod
    def setUpTestData(cls):
        cls.make_world()

    def test_upload_after_needs_update_is_pending_with_history(self):
        ClassSection.objects.filter(pk=self.section.pk).update(
            syllabi_status='needs update', syllabi_status_changed_on={'note': 'Fix'})
        section = ClassSection.objects.get(pk=self.section.pk)
        before = section.history.count()
        ClassSectionSyllabi.objects.create(media='new.pdf').class_sections.add(section)
        section.refresh_from_db()
        self.assertEqual(section.syllabi_status, 'pending review')
        self.assertEqual(section.syllabi_status_changed_on, {})
        self.assertEqual(section.history.count(), before + 1)

    def test_adding_a_section_leaves_the_files_other_sections(self):
        other = ClassSection.objects.create(
            course=self.course, term=self.term, class_number='S2', section_number='01',
            teacher=self.teacher)
        syllabus = ClassSectionSyllabi.objects.create(media='shared.pdf')
        syllabus.class_sections.add(self.section)
        ClassSection.objects.filter(pk=self.section.pk).update(syllabi_status='reviewed')
        syllabus.class_sections.add(other)
        self.section.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.section.syllabi_status, 'reviewed')
        self.assertEqual(other.syllabi_status, 'pending review')

    def test_reverse_add(self):
        syllabus = ClassSectionSyllabi.objects.create(media='rev.pdf')
        self.section.classsectionsyllabi_set.add(syllabus)
        self.section.refresh_from_db()
        self.assertEqual(self.section.syllabi_status, 'pending review')
