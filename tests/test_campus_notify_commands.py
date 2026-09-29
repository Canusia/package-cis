"""MC-11 (#35): notification commands work one campus at a time.

The cron fan-out (MC-04) runs each scheduled command once per campus inside
campus_context(); the notify commands process only that campus's records, so
each email goes out with its own campus's settings (MC-05) and links (MC-10).
The commands are CampusCommands, so a manual run takes --campus.
"""
import uuid
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

from cis.campus_context import NoCampusContext, campus_context, scope_to_current_campus
from cis.management.campus_command import CampusCommand
from cis.models.course import Campus, Cohort, Course
from cis.models.section import ClassSection
from cis.models.term import AcademicYear, Term

NOTIFY_COMMANDS = (
    'notify_rosters_pending_verification', 'notify_missing_syllabi',
    'notify_certificate_renewal', 'notify_school_counselors',
    'notify_homeschool_parents', 'notify_students_notes',
    'notify_students_signatures', 'send_missing_payment_reminder',
)


def _campus(name):
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')


class ScopeHelperTests(TestCase):
    def setUp(self):
        self.c1 = _campus('C1')
        self.c2 = _campus('C2')
        cohort = Cohort.objects.create(name='E', designator='E')
        self.a = Course.objects.create(catalog_number='1', title='A', cohort=cohort, campus=self.c1)
        self.b = Course.objects.create(catalog_number='2', title='B', cohort=cohort, campus=self.c2)

    def test_single_campus_is_unscoped(self):
        self.assertEqual(scope_to_current_campus(Course.objects.all(), 'campus').count(), 2)

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_narrows_to_the_current_campus(self):
        with campus_context(self.c2):
            self.assertEqual(list(scope_to_current_campus(Course.objects.all(), 'campus')), [self.b])

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_without_a_campus_raises(self):
        with self.assertRaises(NoCampusContext):
            scope_to_current_campus(Course.objects.all(), 'campus')


class NotifyCommandsAreCampusCommandsTests(TestCase):
    def test_each_takes_campus(self):
        from django.core.management import load_command_class
        for name in NOTIFY_COMMANDS:
            with self.subTest(command=name):
                self.assertIsInstance(load_command_class('cis', name), CampusCommand)

    @override_settings(MULTI_CAMPUS=True)
    def test_active_context_satisfies_campus(self):
        campus = _campus('C')
        seen = []

        class Probe(CampusCommand):
            def handle(self, *args, **options):
                from cis.campus_context import current_campus
                seen.append(current_campus())

        with campus_context(campus):
            Probe().execute(verbosity=0, no_color=True, force_color=False,
                            skip_checks=True, campus=None)
        self.assertEqual(seen, [campus])


@override_settings(MULTI_CAMPUS=True)
class RosterReminderCampusTests(TestCase):
    def setUp(self):
        self.c1 = _campus('C1')
        self.c2 = _campus('C2')
        cohort = Cohort.objects.create(name='E', designator='E')
        for campus, crn in ((self.c1, 'C1-100'), (self.c2, 'C2-200')):
            course = Course.objects.create(
                catalog_number=crn, title=crn, cohort=cohort, campus=campus)
            with campus_context(campus):
                year = AcademicYear.objects.create(name=f'AY-{crn}')
                term = Term.objects.create(academic_year=year, code=crn, label=crn)
                ClassSection.objects.create(
                    course=course, term=term, class_number=crn,
                    roster_status='Pending Verification')

    def test_each_pass_reminds_only_its_campus(self):
        """Runs the real roster reminder once per campus and records which
        sections it considered (teacher stubbed so none is skipped)."""
        considered = []

        def record(section):
            considered.append((str(section.course.campus_id), section.class_number))
            return False  # no email

        with mock.patch.object(ClassSection, 'teacher', new=True, create=True), \
                mock.patch.object(ClassSection, 'needs_roster_verification_reminder',
                                  autospec=True, side_effect=record), \
                mock.patch('cis.settings.roster_verification.roster_verification.from_db',
                           return_value={}):
            for campus in (self.c1, self.c2):
                with campus_context(campus):
                    ClassSection.notify_sections_pending_roster_verification()

        self.assertEqual(considered, [(str(self.c1.id), 'C1-100'),
                                      (str(self.c2.id), 'C2-200')])
