"""Tests for StudentRegistrationQuerySet.pending_sis_mirror and the
is_held_for_parent_consent property — the single source of truth for
"which registrations are queued for the SIS mirror".
"""

import uuid
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.section import StudentRegistration, ClassSection
from cis.models.student import Student
from cis.models.course import Course, Cohort
from cis.models.term import Term, AcademicYear
from cis.serializers.registration import PendingSisMirrorRegistrationSerializer
from cis.tests.tenant_support import requires_tenant_service


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


def make_registration(status, needs_mirroring):
    """Builds a minimal StudentRegistration, following the fixture pattern
    in test_mirror_to_sis.py's MirrorStatusSyncTests.setUp.
    """
    Group.objects.get_or_create(name='student')
    if not CustomUser.objects.filter(username='cron').exists():
        CustomUser.objects.create_user(
            username='cron', email='cron@example.com', password='x')

    short = uuid.uuid4().hex[:8]

    cohort = Cohort.objects.create(name=f'Cohort-{short}', designator='A')
    course = Course.objects.create(
        catalog_number='001', title='Descriptive Astronomy',
        name=f'A {short}', cohort=cohort)
    ay = AcademicYear.objects.create(name=f'AY-{short}')
    term = Term.objects.create(label=f'Term-{short}', code=short, academic_year=ay)

    # meta={} (no reportingAcademicPeriod) => eligibility gate is skipped.
    section = ClassSection.objects.create(
        course=course, term=term,
        class_number=f'A-{short}', section_number='3428',
        external_sis_id=uuid.uuid4(), meta={},
    )

    student_user = CustomUser.objects.create_user(
        username=f'stu-{short}', email=f'{short}@example.com', password='x',
        first_name='Avi', last_name='Codtest')
    student = Student.objects.create(user=student_user, sis_id=uuid.uuid4())

    return StudentRegistration.objects.create(
        student=student, class_section=section,
        status=status, status_changed_on={}, needs_mirroring=needs_mirroring,
    )


class PendingSisMirrorQuerySetTests(TestCase):
    def test_filters_by_status_and_needs_mirroring(self):
        r_ok = make_registration(status='enrolled', needs_mirroring=True)
        make_registration(status='enrolled', needs_mirroring=False)   # excluded: not flagged
        make_registration(status='applied', needs_mirroring=True)     # excluded: status not a trigger
        qs = StudentRegistration.objects.pending_sis_mirror(['enrolled'])
        self.assertEqual(list(qs), [r_ok])

    def test_trigger_statuses_defaults_to_config(self):
        with patch('cis.settings.registration_status_email.registration_status_email.from_db',
                   return_value={'sis_mirror_trigger': ['enrolled']}):
            r_ok = make_registration(status='enrolled', needs_mirroring=True)
            self.assertIn(r_ok, StudentRegistration.objects.pending_sis_mirror())


class ConsentHoldTests(TestCase):
    def test_not_held_when_step_off(self):
        r = make_registration(status='enrolled', needs_mirroring=True)
        with patch('student_onboarding.step_registry.get', return_value=None):
            self.assertFalse(r.is_held_for_parent_consent)

    def test_held_when_step_on_and_unsigned(self):
        r = make_registration(status='enrolled', needs_mirroring=True)
        with patch('student_onboarding.step_registry.get', return_value=object()), \
             patch.object(type(r), 'has_signed_parent_consent', new_callable=lambda: property(lambda self: False)):
            self.assertTrue(r.is_held_for_parent_consent)

    def test_not_held_when_step_on_and_signed(self):
        r = make_registration(status='enrolled', needs_mirroring=True)
        with patch('student_onboarding.step_registry.get', return_value=object()), \
             patch.object(type(r), 'has_signed_parent_consent',
                          new_callable=lambda: property(lambda self: True)):
            self.assertFalse(r.is_held_for_parent_consent)


class SerializerTests(TestCase):
    def test_will_send_true_and_status_display_label_when_step_off(self):
        r = make_registration(status='enrolled', needs_mirroring=True)
        with patch('student_onboarding.step_registry.get', return_value=None):
            data = PendingSisMirrorRegistrationSerializer(r).data
        self.assertTrue(data['will_send'])
        self.assertEqual(data['parent_consent'], 'N/A')
        self.assertEqual(data['status_display'], r.get_status)


class CommandSelectionMatchesSourceOfTruthTests(TestCase):
    def test_command_module_has_no_local_consent_helper(self):
        import cis.management.commands.send_registrations_to_sis as mod
        self.assertFalse(hasattr(mod, '_consent_blocks'),
                         'consent logic must live on the model, not the command')


class PageRenderTests(TestCase):
    """End-to-end render checks for the Pending SIS Mirror tab page and its
    DataTables JSON feed."""

    def setUp(self):
        self._saved = _disconnect_login_signal()

        Group.objects.get_or_create(name='student')
        ce_group, _ = Group.objects.get_or_create(name='ce')

        academic_year = AcademicYear.objects.create(name='2025-2026-PSM')
        Term.objects.create(
            label='Fall 2025 PSM', code='F25PSM', academic_year=academic_year)

        if not CustomUser.objects.filter(username='cron').exists():
            CustomUser.objects.create_user(
                username='cron', email='cron@example.com', password='x')

        self.user = CustomUser.objects.create_superuser(
            username='psmtest', email='psmtest@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)

        self.trigger_patcher = patch(
            'cis.settings.registration_status_email.registration_status_email.from_db',
            return_value={'sis_mirror_trigger': ['enrolled']})
        self.trigger_patcher.start()

        self.registration = make_registration(status='enrolled', needs_mirroring=True)

    def tearDown(self):
        self.trigger_patcher.stop()
        _reconnect_login_signal(self._saved)

    @requires_tenant_service('pending_sis_mirror_table')
    def test_page_renders_200(self):
        url = reverse('cis:registrations_pending_mirror')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'tbl_pending_mirror', resp.content)

    def _dt_params(self, order_col_index=1, order_dir='asc', search=''):
        """Reproduce the DataTables server-side request the browser sends,
        deriving each column's data/name/orderable/searchable from the tenant
        service config so this test guards the config's actual data-name values.
        """
        import re
        from myce_tenant_configs.services import pending_sis_mirror_table as tbl
        cols = tbl._PROFILES['pending_mirror']['columns']
        params = {
            'format': 'datatables', 'draw': '1', 'start': '0', 'length': '30',
            'search[value]': search, 'search[regex]': 'false',
            'order[0][column]': str(order_col_index), 'order[0][dir]': order_dir,
        }
        for i, key in enumerate(cols):
            th = tbl.COLUMN_HEADER_HTML[key]
            m_data = re.search(r'data-data="([^"]*)"', th)
            m_name = re.search(r'data-name="([^"]*)"', th)
            # The select column's non-orderable/non-searchable state comes from
            # the JS column def (not the <th>); reflect that here.
            if key == 'select':
                orderable = searchable = 'false'
            else:
                orderable = 'false' if 'data-orderable="false"' in th else 'true'
                searchable = 'false' if 'data-searchable="false"' in th else 'true'
            params[f'columns[{i}][data]'] = m_data.group(1) if m_data else str(i)
            params[f'columns[{i}][name]'] = m_name.group(1) if m_name else ''
            params[f'columns[{i}][orderable]'] = orderable
            params[f'columns[{i}][searchable]'] = searchable
            params[f'columns[{i}][search][value]'] = ''
            params[f'columns[{i}][search][regex]'] = 'false'
        return params

    def test_api_order_by_student_column_200(self):
        """Regression: default order is the student column (index 1). Its
        data-name must resolve to a real ORM field or rest_framework_datatables
        raises FieldError building order_by()."""
        url = reverse('cis:pending_sis_mirror_registrations-list')
        resp = self.client.get(url, self._dt_params(order_col_index=1))
        self.assertEqual(resp.status_code, 200, resp.content[:400])

    @requires_tenant_service('pending_sis_mirror_table')
    def test_api_order_by_each_orderable_column_200(self):
        from myce_tenant_configs.services import pending_sis_mirror_table as tbl
        cols = tbl._PROFILES['pending_mirror']['columns']
        url = reverse('cis:pending_sis_mirror_registrations-list')
        for i, key in enumerate(cols):
            th = tbl.COLUMN_HEADER_HTML[key]
            if key == 'select' or 'data-orderable="false"' in th:
                continue
            resp = self.client.get(url, self._dt_params(order_col_index=i))
            self.assertEqual(resp.status_code, 200,
                             f'order by {key} -> {resp.status_code}: {resp.content[:300]}')

    def test_api_global_search_200(self):
        """Global search filters across every searchable column's data-name;
        each must be a real ORM path."""
        url = reverse('cis:pending_sis_mirror_registrations-list')
        resp = self.client.get(url, self._dt_params(search='smith'))
        self.assertEqual(resp.status_code, 200, resp.content[:400])

    def test_api_feed_200(self):
        url = reverse('cis:pending_sis_mirror_registrations-list') + '?format=datatables'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
