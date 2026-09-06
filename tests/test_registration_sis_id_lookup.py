"""Registration-detail 'Look up Section Registration ID from SIS' action —
tenant-service helpers, action handler, dispatch, and detail-page wiring."""
import uuid
from unittest import mock

from django.conf import settings
from django.test import TestCase

from cis.tests.tenant_support import (
    requires_tenant_service, tenant_service_module)

# ethos_identity is an opt-in tenant module, not a required seam -- nnu ships
# none of it. Importing it at module level made this file a collection-time
# ImportError on such a tenant (ewu#42), so it is resolved lazily and the
# class skips where it is absent. Patch targets are strings for the same
# reason: they resolve when the test runs, which is never on a thin tenant.
ETHOS = f'{settings.TENANT_SERVICES_APP}.services.ethos_identity'
ethos_identity = tenant_service_module('ethos_identity')


@requires_tenant_service('ethos_identity')
class LookupSectionRegistrationIdServiceTests(TestCase):
    def _registration(self, student_sis_id, section_sis_id, current_sis_id=None):
        reg = mock.MagicMock()
        reg.student.sis_id = student_sis_id
        reg.class_section.sis_id = section_sis_id
        reg.sis_id = current_sis_id
        return reg

    @mock.patch(f'{ETHOS}.get_ethos_client')
    def test_lookup_returns_guid_from_client(self, mock_client):
        mock_client.return_value.get_section_registration_id.return_value = 'FOUND-GUID'
        reg = self._registration('STU-GUID', 'SEC-GUID')

        result = ethos_identity.lookup_section_registration_id(reg)

        self.assertEqual(result, 'FOUND-GUID')
        mock_client.return_value.get_section_registration_id.assert_called_once_with(
            registrant_id='STU-GUID', section_id='SEC-GUID')

    @mock.patch(f'{ETHOS}.get_ethos_client')
    def test_lookup_returns_none_when_missing_student_sis_id(self, mock_client):
        reg = self._registration(None, 'SEC-GUID')
        self.assertIsNone(ethos_identity.lookup_section_registration_id(reg))
        mock_client.assert_not_called()

    @mock.patch(f'{ETHOS}.get_ethos_client')
    def test_lookup_returns_none_when_missing_section_sis_id(self, mock_client):
        reg = self._registration('STU-GUID', None)
        self.assertIsNone(ethos_identity.lookup_section_registration_id(reg))
        mock_client.assert_not_called()

    def test_apply_rejects_invalid_uuid(self):
        reg = self._registration('STU', 'SEC')
        changes, error = ethos_identity.apply_section_registration_id(reg, 'not-a-uuid')
        self.assertEqual(changes, [])
        self.assertEqual(error, 'Invalid SIS ID')
        reg.save.assert_not_called()

    def test_apply_noop_when_already_set(self):
        guid = str(uuid.uuid4())
        reg = self._registration('STU', 'SEC', current_sis_id=guid)
        changes, error = ethos_identity.apply_section_registration_id(reg, guid)
        self.assertEqual(changes, [])
        self.assertIsNone(error)
        reg.save.assert_not_called()

    def test_apply_saves_new_guid(self):
        guid = str(uuid.uuid4())
        reg = self._registration('STU', 'SEC', current_sis_id=None)
        changes, error = ethos_identity.apply_section_registration_id(
            reg, guid, actor='someuser')
        self.assertIsNone(error)
        self.assertEqual(changes, [f'sis_id -> {guid}'])
        self.assertEqual(reg.sis_id, guid)
        reg.save.assert_called_once_with(update_fields=['sis_id'])


import json
from django.test import RequestFactory
from django.contrib.auth.models import Group

from cis.models import CustomUser
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.course import Course, Cohort
from cis.models.term import Term, AcademicYear
from myce.component_registry.registration import registration_actions


def _make_registration_graph():
    """Minimal StudentRegistration graph. Returns the StudentRegistration."""
    Group.objects.get_or_create(name='student')
    CustomUser.objects.get_or_create(
        username='cron', defaults={'email': 'cron@example.com'})
    ay = AcademicYear.objects.create(name='2025-2026')
    term = Term.objects.create(label='Fall 2025', code='F25', academic_year=ay)
    cohort = Cohort.objects.create(name='Astronomy', designator='A')
    course = Course.objects.create(
        catalog_number='001', title='Descriptive Astronomy', name='A 001', cohort=cohort)
    section = ClassSection.objects.create(
        course=course, term=term, class_number=99001, section_number='001')
    suser = CustomUser.objects.create_user(
        username='sregstudent', email='sregstudent@example.com', password='x')
    student = Student.objects.create(user=suser)
    return StudentRegistration.objects.create(
        student=student, class_section=section, status_changed_on={})


class RegistrationActionHandlerTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.reg = _make_registration_graph()
        self.actor = CustomUser.objects.create_superuser(
            username='ceactor', email='ceactor@example.com', password='x')

    def _post(self, data):
        req = self.factory.post('/ce/registration/bulk_actions', data)
        req.user = self.actor
        return req

    @mock.patch('cis.actions.registration.get_tenant_service')
    def test_lookup_step_returns_modal(self, mock_get_service):
        # Give the registration the two GUIDs the guard requires.
        self.reg.student.sis_id = str(uuid.uuid4())
        self.reg.student.save(update_fields=['sis_id'])
        self.reg.class_section.external_sis_id = str(uuid.uuid4())
        self.reg.class_section.save(update_fields=['external_sis_id'])

        svc = mock_get_service.return_value
        svc.lookup_section_registration_id.return_value = 'FOUND-REG-GUID'

        from cis.actions.registration import lookup_section_registration_id
        resp = lookup_section_registration_id(
            self._post({'ids[]': [str(self.reg.id)]}))

        payload = json.loads(resp.content)
        self.assertEqual(payload['outcome'], 'modal')
        self.assertIn('FOUND-REG-GUID', payload['html'])

    @mock.patch('cis.actions.registration.get_tenant_service')
    def test_lookup_step_warns_when_no_match(self, mock_get_service):
        self.reg.student.sis_id = str(uuid.uuid4())
        self.reg.student.save(update_fields=['sis_id'])
        self.reg.class_section.external_sis_id = str(uuid.uuid4())
        self.reg.class_section.save(update_fields=['external_sis_id'])
        mock_get_service.return_value.lookup_section_registration_id.return_value = None

        from cis.actions.registration import lookup_section_registration_id
        resp = lookup_section_registration_id(
            self._post({'ids[]': [str(self.reg.id)]}))

        payload = json.loads(resp.content)
        self.assertEqual(payload['outcome'], 'alert')
        self.assertEqual(payload['status'], 'warning')

    @mock.patch('cis.actions.registration.get_tenant_service')
    def test_confirmed_step_saves_and_calls_back(self, mock_get_service):
        guid = str(uuid.uuid4())
        svc = mock_get_service.return_value
        svc.apply_section_registration_id.return_value = ([f'sis_id -> {guid}'], None)

        from cis.actions.registration import lookup_section_registration_id
        resp = lookup_section_registration_id(self._post({
            'ids[]': [str(self.reg.id)],
            'action_confirmed': '1',
            'new_sis_id': guid,
        }))

        payload = json.loads(resp.content)
        self.assertEqual(payload['outcome'], 'call')
        self.assertEqual(payload['fn'], 'onActionComplete')
        svc.apply_section_registration_id.assert_called_once()

    @mock.patch('cis.actions.registration.get_tenant_service')
    def test_dispatch_routes_to_handler(self, mock_get_service):
        mock_get_service.return_value.lookup_section_registration_id.return_value = None
        req = self._post({'ids[]': [str(self.reg.id)]})
        resp = registration_actions.dispatch(req, 'lookup_section_registration_id')
        # Missing section/student GUID → guard fires before the service call.
        payload = json.loads(resp.content)
        self.assertEqual(payload['outcome'], 'alert')


from django.contrib.auth.signals import user_logged_in
from django.urls import reverse


class RegistrationDetailActionsDropdownTests(TestCase):
    def setUp(self):
        # django_login_history's post_login receiver crashes on the test
        # client's missing REMOTE_ADDR — disconnect it for the test.
        self._saved = list(user_logged_in.receivers)
        user_logged_in.receivers = []
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.reg = _make_registration_graph()
        self.user = CustomUser.objects.create_superuser(
            username='cedetail', email='cedetail@example.com', password='x')
        # /ce/registration/<id> is gated by user_passes_test(user_has_cis_role),
        # which checks group membership directly (not is_superuser) — mirrors
        # the precedent in test_registration_tabs.py.
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)

    def tearDown(self):
        user_logged_in.receivers = self._saved

    def test_detail_page_shows_lookup_action(self):
        resp = self.client.get(reverse('cis:registration', args=[self.reg.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('Look up Section Registration ID', body)
        self.assertIn("'lookup_section_registration_id'", body)
        self.assertIn('registration_bulk_actions', body)
