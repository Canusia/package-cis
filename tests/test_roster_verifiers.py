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
    HSAdminPerm, HSAdministrator, HSAdministratorPosition, HSPosition)
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
            role = HSAdministratorPosition.objects.create(
                hsadmin=hsadmin, highschool=school, position=position, status=status)
            if flag == 'Yes':
                role.grant(HSAdminPerm.VERIFY_ROSTER)
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

    # -- digests ------------------------------------------------------------

    def _second_section(self, teacher=True):
        return ClassSection.objects.create(
            course=self.section.course, term=self.section.term, class_number='90003',
            section_number='003', highschool=self.school,
            teacher=self.section.teacher if teacher else None)

    def test_one_digest_per_recipient(self):
        other = self._second_section()
        settings = {**BASE, 'verifiers': ['instructor', 'highschool_admin'],
                    'request_verify_subject': 'Verify {{section_count}}',
                    'request_verify_email': '{{recipient_first_name}}: {{section_list}} [{{class_number}}]',
                    'hsadmin_request_verify_subject': 'HS {{section_count}}',
                    'hsadmin_request_verify_email': '{{recipient_first_name}}: {{section_list}}'}
        with mock.patch(FROM_DB, return_value=settings), mock.patch(SEND) as send:
            sent, emails = ClassSection.send_roster_verification_digests(
                [self.section, other, self.no_teacher])
        self.assertEqual(emails, 2)  # one to the instructor, one to the admin
        by_to = {tuple(c.args[4]): c for c in send.call_args_list}
        teacher_mail = by_to[('teach@example.com',)]
        self.assertEqual(teacher_mail.args[0], 'Verify 2')
        self.assertIn('90001', teacher_mail.args[2])
        self.assertIn('90003', teacher_mail.args[2])
        self.assertIn('[]', teacher_mail.args[1])  # per-class code blank in a multi-class digest
        admin_mail = by_to[('ayes@example.com',)]
        self.assertEqual(admin_mail.args[0], 'HS 3')
        for crn in ('90001', '90002', '90003'):
            self.assertIn(crn, admin_mail.args[2])
        self.assertEqual(sent, {self.section.pk, other.pk, self.no_teacher.pk})

    def test_single_class_digest_keeps_the_per_class_codes(self):
        settings = {**BASE, 'request_verify_email': '{{class_number}} / {{section_count}}'}
        with mock.patch(FROM_DB, return_value=settings), mock.patch(SEND) as send:
            ClassSection.send_roster_verification_digests([self.section])
        self.assertIn('90001 / 1', send.call_args.args[1])

    def test_section_list_escapes_values(self):
        self.school.name = 'A & <B>'
        self.school.save()
        html = ClassSection._roster_section_list([self.section])
        self.assertIn('A &amp; &lt;B&gt;', html)

    def test_reminder_cron_sends_one_digest_for_many_sections(self):
        other = self._second_section()
        ClassSection.objects.filter(pk__in=[self.section.pk, other.pk]).update(
            roster_status='pending verification')
        with self._settings(), mock.patch(SEND) as send:
            summary, log = ClassSection.notify_sections_pending_roster_verification()
        self.assertEqual(_recipients(send), [['teach@example.com']])
        self.assertEqual(sorted(log['notified_crn']), ['90001', '90003'])
        self.assertIn('Sent 1 digest email(s) covering 2 section(s)', summary)

    def test_reminders_skip_class_statuses_not_selected(self):
        other = self._second_section()
        ClassSection.objects.filter(pk__in=[self.section.pk, other.pk]).update(
            roster_status='pending verification')
        ClassSection.objects.filter(pk=other.pk).update(status='C')
        with self._settings(reminder_section_statuses=['A']), mock.patch(SEND) as send:
            _summary, log = ClassSection.notify_sections_pending_roster_verification()
        self.assertEqual(log['notified_crn'], ['90001'])
        self.assertNotIn('90003', send.call_args.args[2])

    def test_no_class_status_selected_reminds_every_class(self):
        other = self._second_section()
        ClassSection.objects.filter(pk__in=[self.section.pk, other.pk]).update(
            roster_status='pending verification')
        ClassSection.objects.filter(pk=other.pk).update(status='C')
        with self._settings(reminder_section_statuses=[]), mock.patch(SEND):
            _summary, log = ClassSection.notify_sections_pending_roster_verification()
        self.assertEqual(sorted(log['notified_crn']), ['90001', '90003'])

    def test_bulk_change_sends_one_digest(self):
        from django.http import QueryDict
        from cis.forms.section import BulkRosterStatusChangeForm
        other = self._second_section()
        data = QueryDict(mutable=True)
        data.setlist('record_ids', [str(self.section.pk), str(other.pk)])
        data.update({'new_roster_status': 'pending verification', 'email_instructors': '1',
                     'action': 'change_roster_status'})
        form = BulkRosterStatusChangeForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        request = RequestFactory().post('/')
        request.user = self.teacher_user
        with self._settings(), mock.patch(SEND) as send:
            form.save(request)
        self.assertEqual(_recipients(send), [['teach@example.com']])

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

    def test_hs_admin_report_confirms_to_the_admin_and_the_instructor(self):
        with self._settings(), mock.patch(SEND) as send:
            self._report(self.section, self.admin_user)
        self.section.refresh_from_db()
        self.assertEqual(self.section.roster_status, 'accurate')
        confirmations = [c for c in send.call_args_list if c.args[0] == 'Thanks']
        self.assertEqual([c.args[4] for c in confirmations],
                         [['ayes@example.com'], ['teach@example.com']])
        # Both copies name the admin who reported.
        for call in confirmations:
            self.assertIn('Got it Ayes', call.args[1])
        staff = [c for c in send.call_args_list if c.args[0] == 'Roster changed']
        self.assertIn('Accurate'.lower(), staff[0].args[1].lower())
        self.assertIn('Admin', staff[0].args[1])

    def test_report_on_a_section_without_a_teacher_confirms_to_the_admin_only(self):
        with self._settings(), mock.patch(SEND) as send:
            self._report(self.no_teacher, self.admin_user, answer='2')
        self.no_teacher.refresh_from_db()
        self.assertEqual(self.no_teacher.roster_status, 'inaccurate')
        confirmations = [c.args[4] for c in send.call_args_list if c.args[0] == 'Thanks']
        self.assertEqual(confirmations, [['ayes@example.com']])

    def test_instructor_report_confirms_once(self):
        with self._settings(), mock.patch(SEND) as send:
            self._report(self.section, self.teacher_user)
        confirmations = [c.args[4] for c in send.call_args_list if c.args[0] == 'Thanks']
        self.assertEqual(confirmations, [['teach@example.com']])

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
            position=HSPosition.objects.create(name='Principal'), status='Active')
        self.role.grant(HSAdminPerm.VERIFY_ROSTER)

    def test_can_verify_roster_follows_the_flag_and_status(self):
        self.assertTrue(self.admin.can_verify_roster(self.school.id))
        self.assertEqual(list(self.admin.get_roster_highschools()), [self.school])
        self.role.status = 'Inactive'
        self.role.save()
        self.role.refresh_from_db()
        self.assertEqual(self.role.codenames(), {HSAdminPerm.VERIFY_ROSTER})  # kept while Inactive
        self.assertFalse(self.admin.can_verify_roster(self.school.id))


class RosterStatusesSettingTests(TestCase):
    """Which registration statuses the rosters list (none chosen = all)."""

    def setUp(self):
        from cis.models.section import StudentRegistration
        from cis.models.student import Student
        CustomUser.objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        Group.objects.get_or_create(name='student')
        cohort = Cohort.objects.create(name='Eng', designator='ENG')
        self.section = ClassSection.objects.create(
            course=Course.objects.create(catalog_number='101', title='Comp', cohort=cohort),
            term=Term.objects.create(
                academic_year=AcademicYear.objects.create(name='2026-2027'),
                code='F26', label='Fall 2026'),
            class_number='91001', section_number='001')
        self.regs = {}
        for status in ('registered', 'applied', 'dropped'):
            user = CustomUser.objects.create_user(
                username=f's_{status}', email=f's_{status}@example.com', password='x')
            self.regs[status] = StudentRegistration.objects.create(
                student=Student.objects.create(user=user), class_section=self.section,
                status=status, status_changed_on={})

    def _statuses(self, statuses):
        return mock.patch(FROM_DB, return_value={'roster_statuses': statuses})

    def test_none_selected_lists_every_status(self):
        from cis.settings.roster_verification import roster_registration_statuses
        with self._statuses([]):
            self.assertEqual(roster_registration_statuses(), [])
            self.assertEqual(set(self.section.roster_registrations()), set(self.regs.values()))

    def test_selected_statuses_only(self):
        with self._statuses(['registered', 'applied']):
            self.assertEqual(set(self.section.roster_registrations()),
                             {self.regs['registered'], self.regs['applied']})

    def _pdf_students(self):
        captured = {}

        class FakeTemplate:
            def render(self, ctx):
                captured.update(ctx)
                return ''

        with mock.patch('cis.models.section.get_template', return_value=FakeTemplate()), \
                mock.patch.dict('sys.modules', {'pdfkit': mock.MagicMock()}):
            try:
                self.section.download_roster_pdf()
            except Exception:
                pass
        return set(captured.get('students') or [])

    def test_pdf_keeps_registered_only_when_none_selected(self):
        with self._statuses([]):
            self.assertEqual(self._pdf_students(), {self.regs['registered']})

    def test_pdf_follows_the_selected_statuses(self):
        with self._statuses(['applied', 'registered']):
            self.assertEqual(self._pdf_students(), {self.regs['registered'], self.regs['applied']})

    def test_setting_offers_the_registration_statuses(self):
        from cis.models.section import StudentRegistration
        field = SettingForm().fields['roster_statuses']
        self.assertEqual(list(field.choices), list(StudentRegistration.STATUS_OPTIONS))
        self.assertFalse(field.required)


class PendingRosterVerificationQuerySetTests(TestCase):
    """ClassSection.objects.pending_roster_verification(): the shared rule for
    reminders and dashboards (class statuses, terms incl. sub-terms, tenant
    hook)."""

    def setUp(self):
        ay = AcademicYear.objects.create(name='2026-2027')
        self.active = Term.objects.create(academic_year=ay, code='300', label='Fall Quarter')
        self.sub = Term.objects.create(academic_year=ay, code='290', label='Fall Semester',
                                       parent=self.active)
        self.registration = Term.objects.create(academic_year=ay, code='400', label='Spring')
        self.old = Term.objects.create(academic_year=ay, code='100', label='Last Year')
        course = Course.objects.create(
            catalog_number='101', title='Comp',
            cohort=Cohort.objects.create(name='Eng', designator='ENG'))

        def section(term, crn, status='A'):
            return ClassSection.objects.create(
                course=course, term=term, class_number=crn, section_number='001',
                roster_status='pending verification', status=status)

        self.on_sub = section(self.sub, '1')
        self.on_registration = section(self.registration, '2')
        self.on_old = section(self.old, '3')
        self.cancelled = section(self.sub, '4', status='C')
        self.verified = section(self.sub, '5')
        ClassSection.objects.filter(pk=self.verified.pk).update(roster_status='accurate')

        patches = [
            mock.patch('cis.utils.active_term', return_value=self.active),
            mock.patch('cis.utils.registration_terms',
                       return_value=Term.objects.filter(pk=self.registration.pk)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _crns(self, values):
        qs = ClassSection.objects.all().pending_roster_verification(values)
        return sorted(qs.values_list('class_number', flat=True))

    def test_default_is_active_and_registration_terms_with_sub_terms(self):
        self.assertEqual(self._crns({}), ['1', '2', '4'])

    def test_term_choices(self):
        self.assertEqual(self._crns({'reminder_terms': 'active'}), ['1', '4'])
        self.assertEqual(self._crns({'reminder_terms': 'registration'}), ['2'])
        self.assertEqual(self._crns({'reminder_terms': 'all'}), ['1', '2', '3', '4'])

    def test_class_statuses(self):
        self.assertEqual(self._crns({'reminder_section_statuses': ['A']}), ['1', '2'])

    def test_no_terms_configured_skips_the_term_limit(self):
        with mock.patch('cis.utils.active_term', return_value=None), \
                mock.patch('cis.utils.registration_terms', return_value=None), \
                self.assertLogs('cis.settings.roster_verification', 'WARNING'):
            self.assertEqual(self._crns({}), ['1', '2', '3', '4'])

    def test_chains_onto_the_callers_scope(self):
        qs = ClassSection.objects.filter(class_number='2').pending_roster_verification({})
        self.assertEqual(list(qs.values_list('class_number', flat=True)), ['2'])

    def test_tenant_hook_narrows(self):
        def only_registration(queryset, notif_settings):
            return queryset.filter(term=self.registration)

        with mock.patch('cis.services.tenant_services.get_tenant_override',
                        return_value=only_registration) as override:
            self.assertEqual(self._crns({}), ['2'])
        override.assert_called_with('roster_verification', 'pending_roster_sections')

    def test_setting_offers_the_term_choices_with_the_default(self):
        field = SettingForm().fields['reminder_terms']
        self.assertEqual(field.initial, 'active_and_registration')
        self.assertIn(('all', 'All terms'), list(field.choices))
