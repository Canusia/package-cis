"""New schools get an Active campus link; HighSchool.status derives from links."""
import uuid

from django.conf import settings
from django.test import TestCase, override_settings

from cis.campus_context import campus_context
from cis.models.course import Campus
from cis.models.highschool import HighSchool, HighSchoolCampus


def _campus():
    return Campus.objects.create(
        name=f'C-{uuid.uuid4().hex[:8]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}_{uuid.uuid4().hex[:6]}')


def _hs(name='S', **kw):
    return HighSchool.objects.create(name=name, code=uuid.uuid4().hex[:8], **kw)


def _status(hs):
    return HighSchool.objects.get(pk=hs.pk).status


@override_settings(MULTI_CAMPUS=False)
class NewSchoolSingleCampusTests(TestCase):
    def test_new_school_linked_active_to_deployment_campus(self):
        from cis.campus_context import deployment_campus
        _campus()
        hs = _hs()
        link = HighSchoolCampus.objects.get(highschool=hs)
        self.assertEqual(link.campus, deployment_campus())
        self.assertEqual(link.status, 'Active')

    def test_no_campus_logs_warning_and_no_link(self):
        Campus.objects.all().delete()
        with self.assertLogs('cis.signals.highschool_campus', 'WARNING'):
            hs = _hs()
        self.assertFalse(HighSchoolCampus.objects.filter(highschool=hs).exists())

    def test_existing_link_means_no_second_link(self):
        c = _campus()
        hs = HighSchool(name='X', code='xx1')
        hs.save()  # auto-linked
        hs.save()  # not created: still one
        self.assertEqual(HighSchoolCampus.objects.filter(highschool=hs).count(), 1)
        self.assertEqual(HighSchoolCampus.objects.get(highschool=hs).campus, c)


@override_settings(MULTI_CAMPUS=True)
class NewSchoolMultiCampusTests(TestCase):
    def setUp(self):
        self.a, self.b = _campus(), _campus()

    def test_linked_to_current_campus(self):
        with campus_context(self.b):
            hs = _hs()
        link = HighSchoolCampus.objects.get(highschool=hs)
        self.assertEqual((link.campus, link.status), (self.b, 'Active'))

    def test_no_context_warns_and_leaves_unlinked(self):
        with self.assertLogs('cis.signals.highschool_campus', 'WARNING'):
            hs = _hs()
        self.assertFalse(HighSchoolCampus.objects.filter(highschool=hs).exists())

    def test_created_inside_context_with_prior_link_not_duplicated(self):
        with campus_context(self.a):
            hs = _hs()
        self.assertEqual(HighSchoolCampus.objects.filter(highschool=hs).count(), 1)


@override_settings(MULTI_CAMPUS=True)
class DerivedStatusTests(TestCase):
    def setUp(self):
        self.a, self.b = _campus(), _campus()
        self.hs = _hs()  # no context: unlinked

    def test_unchanged_without_links(self):
        hs = _hs(status='Inactive')
        self.assertEqual(_status(hs), 'Inactive')

    def test_first_active_link_makes_school_active(self):
        HighSchool.objects.filter(pk=self.hs.pk).update(status='Inactive')
        HighSchoolCampus.objects.create(highschool=self.hs, campus=self.a)
        self.assertEqual(_status(self.hs), 'Active')

    def test_any_active_link_keeps_active(self):
        HighSchoolCampus.objects.create(highschool=self.hs, campus=self.a)
        l2 = HighSchoolCampus.objects.create(highschool=self.hs, campus=self.b)
        HighSchoolCampus.objects.filter(pk=l2.pk).first()
        l2.status = 'Inactive'
        l2.save()
        self.assertEqual(_status(self.hs), 'Active')

    def test_all_inactive_makes_school_inactive(self):
        l1 = HighSchoolCampus.objects.create(highschool=self.hs, campus=self.a)
        l1.status = 'Inactive'
        l1.save()
        self.assertEqual(_status(self.hs), 'Inactive')

    def test_delete_recomputes(self):
        l1 = HighSchoolCampus.objects.create(highschool=self.hs, campus=self.a)
        l2 = HighSchoolCampus.objects.create(
            highschool=self.hs, campus=self.b, status='Inactive')
        l1.delete()
        self.assertEqual(_status(self.hs), 'Inactive')
        l2.delete()  # no links left: unchanged
        self.assertEqual(_status(self.hs), 'Inactive')

    def test_written_status_replaced_when_school_has_links(self):
        HighSchoolCampus.objects.create(highschool=self.hs, campus=self.a)
        hs = HighSchool.objects.get(pk=self.hs.pk)
        hs.status = 'Inactive'
        hs.save()
        self.assertEqual(_status(self.hs), 'Active')
        self.assertEqual(hs.status, 'Active')

    def test_written_status_kept_when_school_has_no_links(self):
        hs = HighSchool.objects.get(pk=self.hs.pk)
        hs.status = 'Inactive'
        hs.save()
        self.assertEqual(_status(self.hs), 'Inactive')

    def test_derivation_writes_no_history_row(self):
        before = HighSchool.history.filter(id=self.hs.pk).count()
        HighSchoolCampus.objects.create(
            highschool=self.hs, campus=self.a, status='Inactive')
        self.assertEqual(HighSchool.history.filter(id=self.hs.pk).count(), before)

    def test_raw_save_skipped(self):
        from cis.signals import highschool_campus as sig
        HighSchoolCampus.objects.create(highschool=self.hs, campus=self.a)
        hs = HighSchool.objects.get(pk=self.hs.pk)
        hs.status = 'Inactive'
        sig.derive_status_before_save(HighSchool, hs, raw=True)
        self.assertEqual(hs.status, 'Inactive')
