"""package_ethos#4 (ETHOS-01) follow-ups in cis.

- daily_jobs no longer runs a leftover Ethos debug query (it listed subjects
  with no campus context and returned).
- send_registrations_to_sis is a CampusCommand: --campus runs one campus's
  queue by hand, and a multi-campus run without one is refused.
- The Pending and Failed SIS Mirror feeds (and the failed export) are scoped to
  the ce user's campuses, like the registrations table.
"""
import csv
import io
import uuid
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase, override_settings

from cis.campus_context import campus_context
from cis.management.campus_command import CampusCommand
from cis.models.course import Campus, Cohort, Course
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.term import AcademicYear, Term

User = get_user_model()

TRIGGER = {'sis_mirror_trigger': ['enrolled'], 'sis_mirror_terms': []}


def _sfx():
    return uuid.uuid4().hex[:8]


def _campus():
    return Campus.objects.create(
        name=f'C-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')


def _registration(campus, **fields):
    if campus is None:
        return _build_registration(campus, **fields)
    # Multi-campus refuses to save campus-owned rows outside a campus context.
    with campus_context(campus):
        return _build_registration(campus, **fields)


def _build_registration(campus, **fields):
    cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
    course = Course.objects.create(
        catalog_number='101', title='A', name=f'A {_sfx()}', cohort=cohort, campus=campus)
    ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
    term = Term.objects.create(academic_year=ay, code=_sfx(), label=f'T-{_sfx()}')
    section = ClassSection.objects.create(
        class_number=_sfx(), term=term, course=course, meta={})
    user = User.objects.create_user(
        username=f'stu_{_sfx()}', email=f'{_sfx()}@x.com', password='x')
    student = Student.objects.create(user=user, sis_id=uuid.uuid4())
    defaults = {'status': 'enrolled', 'needs_mirroring': True, 'status_changed_on': {}}
    defaults.update(fields)
    return StudentRegistration.objects.create(
        student=student, class_section=section, **defaults)


def _ce_user(campuses):
    user = User.objects.create_user(
        username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
    user.groups.add(Group.objects.get_or_create(name='ce')[0])
    user.save()
    user.set_process_campuses([str(c.id) for c in campuses])
    return user


class _Fixtures(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@x.com'})
        self.c1 = _campus()
        self.c2 = _campus()
        patcher = mock.patch(
            'cis.settings.registration_status_email.registration_status_email.from_db',
            return_value=TRIGGER)
        patcher.start()
        self.addCleanup(patcher.stop)


class DailyJobsTests(TestCase):
    def test_does_not_call_ethos(self):
        import cis.management.commands.daily_jobs as mod
        self.assertFalse(hasattr(mod, 'Ethos'),
                         'daily_jobs must not import the Ethos client')
        with mock.patch('requests.get') as get, mock.patch('requests.post') as post:
            call_command('daily_jobs', stdout=io.StringIO())
        get.assert_not_called()
        post.assert_not_called()


class SendRegistrationsCampusTests(_Fixtures):
    def _run(self, **options):
        sent = []

        def mirror(record):
            sent.append(record.pk)
            return False, []

        service = SimpleNamespace(mirror_to_sis=mirror)
        with mock.patch(
                'cis.management.commands.send_registrations_to_sis.get_tenant_service',
                return_value=service):
            call_command('send_registrations_to_sis', stdout=io.StringIO(), **options)
        return sent

    def test_is_a_campus_command(self):
        from cis.management.commands.send_registrations_to_sis import Command
        self.assertTrue(issubclass(Command, CampusCommand))

    @override_settings(MULTI_CAMPUS=True)
    def test_campus_option_runs_only_that_campus(self):
        r1 = _registration(self.c1)
        _registration(self.c2)
        self.assertEqual(self._run(campus=self.c1.code), [r1.pk])

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_without_campus_is_refused(self):
        with self.assertRaises(CommandError):
            self._run()

    def test_single_campus_runs_everything(self):
        r1 = _registration(self.c1)
        r2 = _registration(self.c2)
        self.assertEqual(sorted(self._run()), sorted([r1.pk, r2.pk]))


class MirrorFeedCampusScopeTests(_Fixtures):
    def setUp(self):
        super().setUp()
        self.ce = _ce_user([self.c1])

    def _ids(self, viewset_class):
        viewset = viewset_class()
        viewset.request = SimpleNamespace(user=self.ce)
        return set(viewset.get_queryset().values_list('pk', flat=True))

    def test_pending_feed_shows_only_the_users_campuses(self):
        from cis.views.registration_pending_mirror import PendingSisMirrorRegistrationViewSet
        mine = _registration(self.c1)
        shared = _registration(None)
        other = _registration(self.c2)
        ids = self._ids(PendingSisMirrorRegistrationViewSet)
        self.assertIn(mine.pk, ids)
        self.assertIn(shared.pk, ids)
        self.assertNotIn(other.pk, ids)

    def test_failed_feed_shows_only_the_users_campuses(self):
        from cis.views.registration_failed_mirror import FailedMirrorRegistrationViewSet
        mine = _registration(self.c1, last_mirror_status='failed')
        other = _registration(self.c2, last_mirror_status='failed')
        ids = self._ids(FailedMirrorRegistrationViewSet)
        self.assertIn(mine.pk, ids)
        self.assertNotIn(other.pk, ids)

    def test_failed_export_shows_only_the_users_campuses(self):
        from cis.views.registration_failed_mirror import failed_mirror_export
        mine = _registration(self.c1, last_mirror_status='failed')
        other = _registration(self.c2, last_mirror_status='failed')
        request = RequestFactory().get('/')
        request.user = self.ce
        rows = list(csv.reader(io.StringIO(failed_mirror_export(request).content.decode())))
        self.assertEqual(len(rows) - 1, 1, f'expected only {mine.pk}, not {other.pk}')

    def test_superuser_still_sees_every_campus(self):
        from cis.views.registration_pending_mirror import PendingSisMirrorRegistrationViewSet
        self.ce = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')
        r1 = _registration(self.c1)
        r2 = _registration(self.c2)
        ids = self._ids(PendingSisMirrorRegistrationViewSet)
        self.assertTrue({r1.pk, r2.pk} <= ids)
