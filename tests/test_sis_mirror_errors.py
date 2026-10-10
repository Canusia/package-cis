"""SIS mirror errors in Settings: every new error that blocks a registration
mirror is added to the registration status email setting (and the admin is
emailed); the admin ticks the ones that should stop mirroring when they happen
again. Unticked errors keep retrying."""
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
from cis.settings.registration_status_email import (
    record_sis_mirror_errors, registration_status_email, sis_error_key)

ONE_OF = ('One of the following is preventing registration: Course registration status '
          'rules not defined for this section.; Registration is outside of the specified '
          'registration period.; Section status prohibits registration for this section.; '
          'or Registration status does not permit registration on this day.')


def _value():
    return Setting.objects.get(key=registration_status_email.key).value


class RecordSisMirrorErrorsTests(TestCase):
    def setUp(self):
        Setting.objects.update_or_create(
            key=registration_status_email.key,
            defaults={'value': {'sis_mirror_trigger': ['registered'], 'cron': '*/30 * * * *'}})

    def test_new_error_is_added_once(self):
        stop, new = record_sis_mirror_errors('registration', ['Section registration already exists'])
        self.assertEqual((stop, new), (None, ['Section registration already exists']))
        stop, new = record_sis_mirror_errors('registration', ['  section registration ALREADY exists '])
        self.assertEqual((stop, new), (None, []))
        known = _value()['sis_mirror_known_errors']
        self.assertEqual(len(known), 1)
        self.assertEqual(known[0]['message'], 'Section registration already exists')
        self.assertEqual(known[0]['kind'], 'registration')
        self.assertIn('first_seen', known[0])

    def test_existing_settings_are_kept(self):
        record_sis_mirror_errors('registration', ['x'])
        self.assertEqual(_value()['sis_mirror_trigger'], ['registered'])

    def test_ticked_error_is_reported_as_stop(self):
        record_sis_mirror_errors('eligibility', ['You require re-admission prior to registration.'])
        value = _value()
        value['sis_mirror_stop_on_errors'] = [
            sis_error_key('You require re-admission prior to registration.')]
        Setting.objects.filter(key=registration_status_email.key).update(value=value)
        stop, new = record_sis_mirror_errors(
            'eligibility', ['Time tickets prevent registration at this time.',
                            'You require re-admission prior to registration.'])
        self.assertEqual(stop, 'You require re-admission prior to registration.')
        self.assertEqual(new, ['Time tickets prevent registration at this time.'])

    def test_registration_message_is_never_split(self):
        record_sis_mirror_errors('registration', [ONE_OF])
        self.assertEqual([e['message'] for e in _value()['sis_mirror_known_errors']], [ONE_OF])

    def test_creates_the_setting_when_missing(self):
        Setting.objects.filter(key=registration_status_email.key).delete()
        record_sis_mirror_errors('registration', ['x'])
        self.assertEqual(len(_value()['sis_mirror_known_errors']), 1)


class SettingsFormTests(TestCase):
    def setUp(self):
        Setting.objects.update_or_create(
            key=registration_status_email.key,
            defaults={'value': {'sis_mirror_trigger': ['registered']}})
        record_sis_mirror_errors('registration', ['<b>bad</b> thing'])
        record_sis_mirror_errors('eligibility', ['Holds prevent registration.'])
        self.request = RequestFactory().get('/')

    def test_each_known_error_is_a_checkbox(self):
        field = registration_status_email(self.request).fields['sis_mirror_stop_on_errors']
        self.assertFalse(field.required)
        self.assertEqual({v for v, _ in field.choices},
                         {sis_error_key('<b>bad</b> thing'), sis_error_key('Holds prevent registration.')})
        labels = ' '.join(str(label) for _, label in field.choices)
        self.assertIn('Eligibility block', labels)
        self.assertIn('Registration failure', labels)

    def test_markup_in_a_message_is_escaped_on_the_page(self):
        html = str(registration_status_email(self.request)['sis_mirror_stop_on_errors'])
        self.assertIn('&lt;b&gt;bad&lt;/b&gt; thing', html)
        self.assertNotIn('<b>bad</b>', html)

    def test_saving_keeps_errors_collected_meanwhile_and_drops_unknown_keys(self):
        form = registration_status_email(self.request)
        form.cleaned_data = {
            'sis_mirror_trigger': ['registered'], 'cron': '*/30 * * * *',
            'sis_mirror_stop_on_errors': [sis_error_key('Holds prevent registration.'), 'gone'],
        }
        # the mirror adds an error after the admin opened the page
        record_sis_mirror_errors('registration', ['new while editing'])
        form.run_record()
        value = _value()
        self.assertEqual(len(value['sis_mirror_known_errors']), 3)
        self.assertEqual(value['sis_mirror_stop_on_errors'],
                         [sis_error_key('Holds prevent registration.')])


class CronKeepsFailuresQueuedTests(TestCase):
    """The cron used to set needs_mirroring=False after every 'failed to
    process' summary. Failures now stay queued unless their error is ticked."""

    def test_failed_row_stays_queued_after_the_run(self):
        Setting.objects.update_or_create(
            key=registration_status_email.key,
            defaults={'value': {'sis_mirror_trigger': ['registered']}})
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        short = uuid.uuid4().hex[:8]
        section = ClassSection.objects.create(
            course=Course.objects.create(
                catalog_number='001', title='A', name=f'A {short}',
                cohort=Cohort.objects.create(name=f'C {short}', designator='A')),
            term=Term.objects.create(label='T', code='T1',
                                     academic_year=AcademicYear.objects.create(name='AY')),
            class_number=f'A-{short}', section_number='01', external_sis_id=uuid.uuid4(), meta={})
        reg = StudentRegistration.objects.create(
            student=Student.objects.create(
                user=CustomUser.objects.create_user(
                    username=f's-{short}', email=f'{short}@x.com', password='x'),
                sis_id=uuid.uuid4()),
            class_section=section, status='registered', status_changed_on={})
        StudentRegistration.objects.filter(pk=reg.pk).update(needs_mirroring=True)
        with patch('cis.services.tenant_services.get_tenant_service') as svc:
            svc.return_value.mirror_to_sis.return_value = (True, ['S, x - failed to process - boom'])
            call_command('send_registrations_to_sis')
        self.assertTrue(StudentRegistration.objects.get(pk=reg.pk).needs_mirroring)


class NotifyNewErrorsTests(TestCase):
    def _registration(self):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        Setting.objects.update_or_create(
            key=registration_status_email.key,
            defaults={'value': {'sis_mirror_error_notifications': 'admin@example.com'}})
        short = uuid.uuid4().hex[:8]
        return StudentRegistration.objects.create(
            student=Student.objects.create(
                user=CustomUser.objects.create_user(
                    username=f's-{short}', email=f'{short}@x.com', password='x',
                    first_name='S', last_name='T')),
            class_section=ClassSection.objects.create(
                course=Course.objects.create(
                    catalog_number='001', title='A', name=f'A {short}',
                    cohort=Cohort.objects.create(name=f'C {short}', designator='A')),
                term=Term.objects.create(label='T', code='T1',
                                         academic_year=AcademicYear.objects.create(name='AY')),
                class_number=f'A-{short}', section_number='01', meta={}),
            status='applied', status_changed_on={})

    def _setting_record(self):
        try:
            from setting.models import SettingRecord
        except ImportError:
            from setting.setting.models import SettingRecord
        return SettingRecord.objects.create(
            name='registration_status_email', title='Student Registration Change',
            description='x', categories='x')

    def test_new_errors_flag_the_subject_and_link_to_the_settings(self):
        reg = self._registration()
        record = self._setting_record()
        with patch('cis.models.section.send_html_mail') as send:
            reg.notify_sis_mirror_fail(None, 'boom <b>&', new_errors=['boom <b>&'])
        subject, text_body, html_body = send.call_args.args[:3]
        self.assertIn('new error awaiting review', subject)
        self.assertIn('boom', text_body)
        self.assertIn('Stop mirroring when these errors happen again', text_body)
        self.assertRegex(
            text_body, rf'https?://[^\s]+/record_details/?\?report_id={record.id}')
        self.assertIn('boom &lt;b&gt;&amp;', html_body)
        self.assertNotIn('<b>', html_body)

    def test_email_still_goes_out_without_the_link_when_building_it_fails(self):
        from django.core.exceptions import ImproperlyConfigured
        reg = self._registration()
        self._setting_record()
        with patch('cis.campus_context.campus_url', side_effect=ImproperlyConfigured('no site')), \
                patch('cis.models.section.send_html_mail') as send:
            reg.notify_sis_mirror_fail(None, 'boom', new_errors=['boom'])
        send.assert_called_once()
        subject, text_body = send.call_args.args[:2]
        self.assertIn('new error awaiting review', subject)
        self.assertIn('boom', text_body)
        self.assertNotIn('report_id=', text_body)
