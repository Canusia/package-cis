"""Who can verify a class roster (package-cis#69).

The Roster Verification setting chooses the instructor and/or high school
admins (default instructor only). The request and reminders go to whoever is
enabled -- for admins, those whose Active role at the section's school has
Verify Class Rosters -- the confirmation goes to whoever reported, and Debug
mode redirects every one of these emails.
"""
from unittest import mock

from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings

from cis.models import CustomUser
from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition, HSPosition)
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term
from cis.settings.roster_verification import (
    SettingForm, can_verify, get_verifiers)

SEND = 'cis.models.section.send_html_mail'
FROM_DB = 'cis.settings.roster_verification.roster_verification.from_db'

BASE = {
    'mode': 'active',
    'notify_address': 'staff@example.com',
    'request_verify_subject': 'Verify {{class_number}}',
    'request_verify_email': 'Hi {{recipient_first_name}}',
    'hsadmin_request_verify_subject': 'HS verify {{class_number}}',
    'hsadmin_request_verify_email': 'Hello {{recipient_first_name}}, instructor {{teacher_last_name}}',
    'verify_confirmation_subject': 'Thanks',
    'verify_confirmation_email': 'Got it {{reporter_first_name}}',
    'notify_verify_confirmation_subject': 'Roster changed',
    'notify_verify_email': '{{roster_status}} by {{reporter_last_name}}',
    'notify_status': ['accurate', 'inaccurate'],
    'frequency': '3',
}


def _recipients(send):
    return [call.args[4] for call in send.call_args_list]


def _flat(send):
    return sorted(a for call in send.call_args_list for a in call.args[4])


@override_settings(DEBUG=False)
class RosterVerifierTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='highschool_admin')
        # add_note(None, ...) attributes system notes to the 'cron' user.
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})
        cohort = Cohort.objects.create(name='Eng', designator='ENG')
        course = Course.objects.create(
            catalog_number='101', title='Comp', name='ENG 101', cohort=cohort)
        term = Term.objects.create(
            academic_year=AcademicYear.objects.create(name='2026-2027'),
            code='F26', label='Fall 2026')
        self.school = HighSchool.objects.create(name='Central High', code='CEN')
        other = HighSchool.objects.create(name='North High', code='NOR')

        self.teacher_user = CustomUser.objects.create_user(
            username='teach', email='teach@example.com', password='x',
            first_name='Tess', last_name='Teacher')
        teacher = Teacher.objects.create(user=self.teacher_user)

        self.section = ClassSection.objects.create(
            course=course, term=term, class_number='90001', section_number='001',
            highschool=self.school, teacher=teacher)
        self.no_teacher = ClassSection.objects.create(
            course=course, term=term, class_number='90002', section_number='002',
            highschool=self.school)

        position = HSPosition.objects.create(name='Counselor')

        def admin(name, school, status='Active', flag='Yes'):
            user = CustomUser.objects.create_user(
                username=name, email=f'{name}@example.com', password='x',
                first_name=name.title(), last_name='Admin')
            hsadmin = HSAdministrator.objects.create(user=user)
            HSAdministratorPosition.objects.create(
                hsadmin=hsadmin, highschool=school, position=position,
                status=status, meta={'manage_roster_verification': flag})
            return user

        self.admin_yes = admin('ayes', self.school)
        admin('ano', self.school, flag='No')
        admin('aout', other)
        self.admin_user = self.admin_yes

    def _settings(self, **extra):
        return mock.patch(FROM_DB, return_value={**BASE, **extra})

    # -- the setting -------------------------------------------------------

    def test_existing_row_without_the_key_shows_instructor_checked(self):
        form = SettingForm(initial={'mode': 'active'})
        self.assertEqual(form['verifiers'].value(), ['instructor'])

    def test_saving_with_nothing_checked_is_rejected(self):
        form = SettingForm(data={**BASE, 'cron': '10 11 * * *', 'intro': 'x'})
        self.assertFalse(form.is_valid())
        self.assertIn('verifiers', form.errors)

    def test_hs_admins_need_their_templates(self):
        data = {**BASE, 'cron': '10 11 * * *', 'intro': 'x',
                'verifiers': ['highschool_admin'],
                'hsadmin_request_verify_subject': '', 'hsadmin_request_verify_email': ''}
        form = SettingForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('hsadmin_request_verify_email', form.errors)

    def test_verifier_helpers_default_to_instructor(self):
        self.assertEqual(get_verifiers({}), ['instructor'])
        self.assertEqual(get_verifiers({'verifiers': []}), ['instructor'])
        self.assertTrue(can_verify('instructor', {}))
        self.assertFalse(can_verify('highschool_admin', {}))
        self.assertTrue(can_verify('highschool_admin', {'verifiers': ['highschool_admin']}))

    # -- verification request ---------------------------------------------

    def test_default_sends_to_the_instructor_only(self):
        with self._settings(), mock.patch(SEND) as send:
            self.assertTrue(self.section.notify_roster_verifiers())
        self.assertEqual(_recipients(send), [['teach@example.com']])

    def test_hs_admins_enabled_reaches_flagged_active_admins_at_the_school(self):
        with self._settings(verifiers=['instructor', 'highschool_admin']), \
                mock.patch(SEND) as send:
            self.section.notify_roster_verifiers()
        self.assertEqual(_flat(send), ['ayes@example.com', 'teach@example.com'])
        hs_call = [c for c in send.call_args_list if c.args[4] == ['ayes@example.com']][0]
        self.assertEqual(hs_call.args[0], 'HS verify 90001')
        self.assertIn('Hello Ayes, instructor Teacher', hs_call.args[1])

    def test_section_without_a_teacher_still_reaches_hs_admins(self):
        with self._settings(verifiers=['instructor', 'highschool_admin']), \
                mock.patch(SEND) as send:
            self.assertTrue(self.no_teacher.notify_roster_verifiers())
        self.assertEqual(_flat(send), ['ayes@example.com'])

    def test_instructor_disabled_gets_nothing(self):
        with self._settings(verifiers=['highschool_admin']), mock.patch(SEND) as send:
            self.section.notify_roster_verifiers()
        self.assertEqual(_flat(send), ['ayes@example.com'])

    def test_inactive_role_gets_nothing(self):
        HSAdministratorPosition.objects.filter(
            hsadmin__user=self.admin_yes).update(status='Inactive')
        with self._settings(verifiers=['highschool_admin']), mock.patch(SEND) as send:
            self.assertFalse(self.section.notify_roster_verifiers())
        send.assert_not_called()

    def test_debug_mode_redirects_every_recipient(self):
        with self._settings(mode='debug', verifiers=['instructor', 'highschool_admin']), \
                mock.patch(SEND) as send:
            self.section.notify_roster_verifiers()
        self.assertEqual(_recipients(send), [['staff@example.com'], ['staff@example.com']])

    def test_old_method_name_routes_to_every_verifier(self):
        with self._settings(verifiers=['highschool_admin']), mock.patch(SEND) as send:
            self.no_teacher.notify_teacher_on_roster_verification()
        self.assertEqual(_flat(send), ['ayes@example.com'])

    def test_reminder_cron_includes_sections_without_a_teacher(self):
        ClassSection.objects.filter(pk__in=[self.section.pk, self.no_teacher.pk]).update(
            roster_status='pending verification')
        with self._settings(verifiers=['highschool_admin']), mock.patch(SEND) as send:
            summary, log = ClassSection.notify_sections_pending_roster_verification()
        self.assertIn('90002', log['notified_crn'])
        self.assertIn('Failed to send 0', summary)
        self.assertIn('ayes@example.com', _flat(send))

    # -- reporting ----------------------------------------------------------

    def _report(self, section, user, answer='1'):
        from cis.forms.section import ClassSectionRosterStatusForm
        request = RequestFactory().post('/')
        request.user = user
        form = ClassSectionRosterStatusForm(section, {
            'id': str(section.id), 'roster_status': answer, 'message': 'ok',
            'action': 'submit_roster_status'})
        self.assertTrue(form.is_valid(), form.errors)
        form.save(section, request)

    def test_hs_admin_report_confirms_to_the_admin(self):
        with self._settings(), mock.patch(SEND) as send:
            self._report(self.section, self.admin_user)
        self.section.refresh_from_db()
        self.assertEqual(self.section.roster_status, 'accurate')
        confirmations = [c for c in send.call_args_list if c.args[0] == 'Thanks']
        self.assertEqual([c.args[4] for c in confirmations], [['ayes@example.com']])
        self.assertIn('Got it Ayes', confirmations[0].args[1])
        staff = [c for c in send.call_args_list if c.args[0] == 'Roster changed']
        self.assertIn('Accurate'.lower(), staff[0].args[1].lower())
        self.assertIn('Admin', staff[0].args[1])

    def test_report_on_a_section_without_a_teacher_does_not_crash(self):
        with self._settings(), mock.patch(SEND):
            self._report(self.no_teacher, self.admin_user, answer='2')
        self.no_teacher.refresh_from_db()
        self.assertEqual(self.no_teacher.roster_status, 'inaccurate')

    def test_ce_change_still_confirms_to_the_instructor(self):
        with self._settings(), mock.patch(SEND) as send:
            self.section.roster_status = 'accurate'
            self.section.save()
        confirmations = [c.args[4] for c in send.call_args_list if c.args[0] == 'Thanks']
        self.assertEqual(confirmations, [['teach@example.com']])

    def test_confirmation_honours_debug_mode(self):
        with self._settings(mode='debug'), mock.patch(SEND) as send:
            self._report(self.section, self.admin_user)
        self.assertEqual({tuple(r) for r in _recipients(send)}, {('staff@example.com',)})


class RosterStatusFormOverrideTests(TestCase):
    def test_default_form_without_a_tenant_module(self):
        from cis.forms import section as section_forms
        with mock.patch('cis.services.tenant_services.get_tenant_override',
                        return_value=None):
            self.assertIs(section_forms.ClassSectionRosterStatusForm,
                          section_forms.DefaultClassSectionRosterStatusForm)

    def test_tenant_form_wins(self):
        from cis.forms import section as section_forms

        class TenantForm(section_forms.DefaultClassSectionRosterStatusForm):
            pass

        with mock.patch('cis.services.tenant_services.get_tenant_override',
                        return_value=TenantForm) as override:
            self.assertIs(section_forms.ClassSectionRosterStatusForm, TenantForm)
        override.assert_called_once_with('roster_status_form', 'ClassSectionRosterStatusForm')


class RosterFlagRoleTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='highschool_admin')
        self.school = HighSchool.objects.create(name='Central High', code='CEN')
        user = CustomUser.objects.create_user(
            username='a', email='a@example.com', password='x')
        self.admin = HSAdministrator.objects.create(user=user)
        self.role = HSAdministratorPosition.objects.create(
            hsadmin=self.admin, highschool=self.school,
            position=HSPosition.objects.create(name='Principal'), status='Active',
            meta={'manage_roster_verification': 'Yes'})

    def test_role_form_defaults_to_no(self):
        from cis.forms.highschool import HSAdministratorPositionForm
        field = HSAdministratorPositionForm(id='-1', initial={'id': '-1'}).fields[
            'manage_roster_verification']
        self.assertEqual(field.initial, 'No')
        self.assertEqual(field.choices[0][0], 'No')

    def test_can_verify_roster_follows_the_flag_and_status(self):
        self.assertTrue(self.admin.can_verify_roster(self.school.id))
        self.assertEqual(list(self.admin.get_roster_highschools()), [self.school])
        self.role.status = 'Inactive'
        self.role.save()
        self.role.refresh_from_db()
        self.assertEqual(self.role.meta['manage_roster_verification'], 'No')
        self.assertFalse(self.admin.can_verify_roster(self.school.id))
