"""package-cis#110: syllabus review emails and previews read only keys the
Class Syllabi - Review settings form saves (falling back to legacy keys a
tenant may still have stored, then to shipped defaults -- never "None").
"""
import re
import uuid
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import RequestFactory, TestCase

from cis.models.course import Cohort, Course
from cis.models.customuser import CustomUser
from cis.models.section import ClassSection
from cis.models.settings import Setting
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term
from cis.settings.syllabi_review import syllabi_review

KEY = syllabi_review.key
NOTIFY_SEND = 'cis.management.commands.notify_missing_syllabi.send_html_mail'
MODEL_SEND = 'cis.models.section.send_html_mail'


def set_value(value):
    Setting.objects.update_or_create(key=KEY, defaults={'value': value})


class SyllabiFixtureMixin:

    @classmethod
    def make_world(cls):
        sfx = uuid.uuid4().hex[:6]
        Group.objects.get_or_create(name='instructor')
        cls.reviewer = CustomUser.objects.create(
            username=f'rev{sfx}', email=f'rev{sfx}@example.com')
        user = CustomUser.objects.create(
            username=f'inst{sfx}', email=f'inst{sfx}@example.com',
            first_name='Pat', last_name='Lee')
        cls.teacher = Teacher.objects.create(user=user, status='active')
        cohort = Cohort.objects.create(name=f'E{sfx}', designator=f'E{sfx}')
        cls.course = Course.objects.create(
            name=f'ENGL {sfx}', title='English', catalog_number='101',
            cohort=cohort, status='Active')
        year = AcademicYear.objects.create(name=f'AY-{sfx}')
        cls.term = Term.objects.create(
            academic_year=year, code=f'T{sfx}', label=f'Fall {sfx}')
        cls.section = ClassSection.objects.create(
            course=cls.course, term=cls.term, class_number=f'C{sfx}',
            section_number='01', teacher=cls.teacher)


def saved_form_value(**overrides):
    """The value run_record() stores: exactly the form's fields."""
    today = date.today()
    value = {
        'mode': 'active',
        'testers': 'tester@example.com',
        'term': [],
        'starting_date': (today - timedelta(days=1)).strftime('%m/%d/%Y'),
        'ending_date': (today + timedelta(days=1)).strftime('%m/%d/%Y'),
        'cron': '0 6 * * *',
        'pending_upload_email_header': '',
        'missing_syllabus_email_subject': 'MISSING',
        'missing_syllabus_email_message': 'missing {{section_list}}',
        'instructor_message': 'fix: {{note}}',
        'faculty_message': 'faculty note',
        'teacher_email_header': '',
        'needs_update_email_subject': 'NEEDS UPDATE',
        'needs_update_email_message': '{{term}}|{{course}}|{{note}}',
        'reviewed_email_subject': 'REVIEWED',
        'email_message_reviewed': '{{instructor_first_name}}|{{course_name}}|{{term}}',
    }
    value.update(overrides)
    return value


class FormFieldsTests(TestCase):
    """Every key a reader uses is a field on the form, so a save keeps it."""

    def test_reader_keys_are_form_fields(self):
        form = syllabi_review(RequestFactory().get('/'))
        for key in ('missing_syllabus_email_subject', 'missing_syllabus_email_message',
                    'needs_update_email_subject', 'needs_update_email_message',
                    'reviewed_email_subject', 'email_message_reviewed',
                    'instructor_message', 'faculty_message'):
            with self.subTest(key=key):
                self.assertIn(key, form.fields)

    def test_unsaved_fields_are_prefilled_from_legacy_keys(self):
        """A tenant whose copy lives under a legacy key sees it in the form,
        so the next save moves it to the new key instead of dropping it."""
        initial = {'email_subject': 'Old needs update subject',
                   'email_message': 'Old needs update body {{note}}'}
        form = syllabi_review(RequestFactory().get('/'), initial=initial)
        self.assertEqual(form['needs_update_email_subject'].value(),
                         'Old needs update subject')
        self.assertEqual(form['needs_update_email_message'].value(),
                         'Old needs update body {{note}}')

    def test_unsaved_fields_are_prefilled_with_defaults(self):
        form = syllabi_review(RequestFactory().get('/'), initial={})
        for key in ('needs_update_email_subject', 'needs_update_email_message',
                    'reviewed_email_subject', 'email_message_reviewed'):
            with self.subTest(key=key):
                self.assertTrue(form[key].value())

    def test_install_defaults_use_form_keys(self):
        Setting.objects.filter(key=KEY).delete()
        syllabi_review(RequestFactory().get('/')).install()
        stored = syllabi_review.from_db()
        for key in ('missing_syllabus_email_subject', 'missing_syllabus_email_message',
                    'needs_update_email_subject', 'needs_update_email_message',
                    'reviewed_email_subject', 'email_message_reviewed'):
            with self.subTest(key=key):
                self.assertTrue(stored.get(key))


class SaveRoundTripTests(SyllabiFixtureMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.make_world()

    def test_saving_the_form_keeps_every_reader_key(self):
        data = saved_form_value(term=[str(self.term.id)])
        request = RequestFactory().post('/', data)
        form = syllabi_review(request, data=data)
        self.assertTrue(form.is_valid(), form.errors)
        form.run_record()
        stored = syllabi_review.from_db()
        for key in ('needs_update_email_subject', 'needs_update_email_message',
                    'reviewed_email_subject', 'email_message_reviewed',
                    'faculty_message', 'instructor_message'):
            with self.subTest(key=key):
                self.assertEqual(stored.get(key), data[key])


class TemplateLookupTests(TestCase):

    def test_new_key_wins(self):
        set_value(saved_form_value())
        self.assertEqual(syllabi_review.email_template('needs_update'),
                         ('NEEDS UPDATE', '{{term}}|{{course}}|{{note}}'))

    def test_legacy_keys_are_used_when_new_keys_absent(self):
        set_value({'email_subject': 'Legacy subj', 'email_message': 'Legacy body'})
        self.assertEqual(syllabi_review.email_template('needs_update'),
                         ('Legacy subj', 'Legacy body'))

    def test_old_install_defaults_are_not_mistaken_for_needs_update_copy(self):
        """install() used to seed email_subject/email_message with the
        missing-syllabus text; that is not needs-update copy."""
        set_value({'email_subject': 'Missing Syllabi',
                   'email_message': '{{instructor_first_name}}, {{instructor_last_name}}, {{section_list}}, {{term}}'})
        subject, body = syllabi_review.email_template('needs_update')
        self.assertNotEqual(subject, 'Missing Syllabi')
        self.assertNotIn('section_list', body)

    def test_nothing_stored_falls_back_to_defaults_not_none(self):
        set_value({'needs_update_email_subject': None, 'email_message_reviewed': ''})
        for kind in ('missing_syllabus', 'needs_update', 'reviewed'):
            with self.subTest(kind=kind):
                subject, body = syllabi_review.email_template(kind)
                self.assertTrue(subject)
                self.assertTrue(body)
                self.assertNotIn('None', subject + body)


class PreviewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        codes = ('{{instructor_first_name}} {{instructor_last_name}} '
                 '{{section_list}} {{term}} {{course}} {{course_name}} {{note}}')
        set_value(saved_form_value(**{
            'missing_syllabus_email_message': f'missing: {codes}',
            'needs_update_email_message': f'needs: {codes}',
            'email_message_reviewed': f'reviewed: {codes}',
            'instructor_message': f'instructor: {codes}',
            'faculty_message': f'faculty: {codes}',
        }))

    def preview(self, field):
        request = RequestFactory().get(
            '/ce/settings/show_preview/', {'setting': 'syllabi_review', 'field': field})
        form = syllabi_review(request, initial=syllabi_review.from_db())
        return form.preview(request, field)

    def assert_preview(self, field, marker, subject=None):
        response = self.preview(field)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(marker, html)
        self.assertNotIn('None', html)
        for sample in ('Dale', 'Smith', 'ACC 101', 'Fall 2026', 'Add a grading scale'):
            self.assertIn(sample, html)
        if subject:
            self.assertIn(subject, html)

    def test_missing_syllabus_email(self):
        self.assert_preview('email', 'missing:', 'MISSING')

    def test_needs_update_email(self):
        self.assert_preview('email_message', 'needs:', 'NEEDS UPDATE')

    def test_reviewed_email(self):
        self.assert_preview('reviewed_message', 'reviewed:', 'REVIEWED')

    def test_instructor_message(self):
        self.assert_preview('instructor_message', 'instructor:')

    def test_faculty_message(self):
        self.assert_preview('faculty_message', 'faculty:')

    def test_unknown_field_is_400(self):
        self.assertEqual(self.preview('nope').status_code, 400)

    def test_every_preview_link_is_supported(self):
        form = syllabi_review(RequestFactory().get('/'))
        linked = set()
        for field in form.fields.values():
            linked.update(re.findall(
                r"do_bulk_action\(\\?'syllabi_review\\?', \\?'(\w+)\\?'\)",
                str(field.help_text)))
        self.assertTrue(linked)
        for field in linked:
            with self.subTest(field=field):
                self.assertEqual(self.preview(field).status_code, 200)


class NeedsUpdateReminderTests(SyllabiFixtureMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.make_world()
        set_value(saved_form_value(term=[str(cls.term.id)]))
        ClassSection.objects.filter(id=cls.section.id).update(
            syllabi_status='needs update',
            syllabi_status_changed_on={'note': 'Fix grading'})

    def test_reminder_uses_saved_template_term_and_note(self):
        with mock.patch(NOTIFY_SEND) as send:
            call_command('notify_missing_syllabi')
        mails = {c.args[0]: c.args[1] for c in send.call_args_list}
        self.assertEqual(mails.get('NEEDS UPDATE'),
                         f'{self.term}|{self.course}|Fix grading')


class MarkSyllabiEmailTests(SyllabiFixtureMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.make_world()

    def sent(self, action, *args):
        section = ClassSection.objects.get(id=self.section.id)
        with mock.patch(MODEL_SEND) as send:
            getattr(section, action)(*args, updated_by=self.reviewer)
        self.assertEqual(send.call_count, 1)
        subject, text_body = send.call_args.args[:2]
        return subject, text_body

    def test_reviewed_email_uses_form_keys(self):
        set_value(saved_form_value())
        subject, body = self.sent('mark_syllabi_as_reviewed')
        self.assertEqual(subject, 'REVIEWED')
        self.assertEqual(body, f'Pat|{self.course}|{self.term}')

    def test_needs_update_email_uses_form_keys(self):
        set_value(saved_form_value())
        subject, body = self.sent('mark_syllabi_as_needs_update', 'Add policy')
        self.assertEqual(subject, 'NEEDS UPDATE')
        self.assertEqual(body, f'{self.term}|{self.course}|Add policy')

    def test_unconfigured_emails_fall_back_to_defaults(self):
        set_value({'mode': 'active', 'testers': 'tester@example.com'})
        for action, args in (('mark_syllabi_as_reviewed', ()),
                             ('mark_syllabi_as_needs_update', ('Add policy',))):
            with self.subTest(action=action):
                subject, body = self.sent(action, *args)
                self.assertTrue(subject)
                self.assertNotEqual(body.strip(), 'None')
                self.assertIn(str(self.course), body)
