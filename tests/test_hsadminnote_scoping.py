"""PT-9 (revised): /highschool_admin/ajax/ model=hsadminnote is CIS-only.

The hsadminnote add-note form (GET) and note creation (POST) are restricted to
CIS (`ce`) staff. A highschool_admin must NOT be able to open the form for, or
create a note on, ANY HSAdministrator -- including one bound to a high school
they administer. CE staff may note any administrator.
"""
import uuid

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from two_step.models import TwoStep
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition, HSPosition,
)
from cis.models.note import HSAdministratorNote

User = get_user_model()


class HsAdminNoteScopingTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler raises in tests
        # because the request has no usable IP. Disconnect for this case.
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    @classmethod
    def _hs_admin_bound_to(cls, role, *highschools):
        """Create a user (in `role` group) + HSAdministrator bound to each
        given HighSchool via an Active HSAdministratorPosition.
        Returns (user, hsadmin)."""
        suffix = uuid.uuid4().hex[:8]
        user = User.objects.create_user(
            username=f'{role}_{suffix}',
            email=f'{role}_{suffix}@example.com',
            password='x',
            first_name=role.capitalize(),
            last_name=suffix,
        )
        user.groups.add(Group.objects.get(name=role))
        hsadmin = HSAdministrator.objects.create(user=user)
        position = HSPosition.objects.create(name=f'Pos-{suffix}')
        for hs in highschools:
            HSAdministratorPosition.objects.create(
                hsadmin=hsadmin, highschool=hs, position=position,
                status='Active',
            )
        return user, hsadmin

    @classmethod
    def setUpTestData(cls):
        for name in ('ce', 'highschool_admin'):
            Group.objects.get_or_create(name=name)

        cls.url = reverse('highschool_admin:ajax')
        # CE staff reach add_new_note through the ungated /ce/add_new_ajax/
        # endpoint, not /highschool_admin/ajax/ (whose URL wrapper requires the
        # 'highschool_admin' role). Same add_new dispatcher; the per-handler
        # user_has_cis_role gate is what grants CE through.
        cls.ce_url = reverse('cis:add_new_ajax')

        cls.hs_a = HighSchool.objects.create(name='HS Alpha')
        cls.hs_b = HighSchool.objects.create(name='HS Beta')

        # Attacker: highschool_admin bound to HS A only.
        cls.attacker, _ = cls._hs_admin_bound_to('highschool_admin', cls.hs_a)
        # Target admins: one out-of-scope (HS B), one in-scope (HS A).
        _, cls.target_foreign = cls._hs_admin_bound_to(
            'highschool_admin', cls.hs_b)
        _, cls.target_inscope = cls._hs_admin_bound_to(
            'highschool_admin', cls.hs_a)

        # CE administrator (full access).
        cls.ce_user, _ = cls._hs_admin_bound_to('ce')

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')

    def _login_verified(self, user):
        """force_login + mark the client session two-step-verified, so the
        request passes the PT-19 verification_required gate on
        /highschool_admin/ajax/ and reaches the per-handler CIS-role 403."""
        self.client.force_login(user)
        session_key = self.client.session.session_key
        TwoStep.objects.update_or_create(
            session_id=session_key,
            user=user,
            defaults={'verification_code': '123456', 'verified': True},
        )

    def _get_form(self, hsadmin, url=None):
        return self.client.get(url or self.url, {
            'model': 'hsadminnote',
            'parent': str(hsadmin.id),
            'id': '-1',
            'ajax': '1',
        })

    def _post_note(self, hsadmin, note_text, url=None):
        return self.client.post(url or self.url, {
            'model': 'hsadminnote',
            'id': '-1',
            'note': note_text,
            'add_to': str(hsadmin.id),
            'ajax': '1',
        })

    # --- highschool_admin: cross-tenant must be forbidden ---

    def test_cross_tenant_get_form_is_forbidden(self):
        self._login_verified(self.attacker)
        resp = self._get_form(self.target_foreign)
        self.assertEqual(resp.status_code, 403)

    def test_cross_tenant_note_create_is_forbidden(self):
        self._login_verified(self.attacker)
        resp = self._post_note(self.target_foreign, 'cross-tenant write attempt')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(
            HSAdministratorNote.objects.filter(
                hsadmin=self.target_foreign).count(),
            0,
        )

    # --- highschool_admin: in-scope is ALSO forbidden (CIS-only) ---

    def test_in_scope_get_form_is_forbidden(self):
        self._login_verified(self.attacker)
        resp = self._get_form(self.target_inscope)
        self.assertEqual(resp.status_code, 403)

    def test_in_scope_note_create_is_forbidden(self):
        self._login_verified(self.attacker)
        resp = self._post_note(self.target_inscope, 'in-scope write attempt')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(
            HSAdministratorNote.objects.filter(
                hsadmin=self.target_inscope).count(),
            0,
        )

    # --- CE: any admin must be allowed ---

    def test_ce_can_get_form_for_any_admin(self):
        self.client.force_login(self.ce_user)
        resp = self._get_form(self.target_foreign, url=self.ce_url)
        self.assertNotEqual(resp.status_code, 403)

    def test_ce_can_create_note_for_any_admin(self):
        self.client.force_login(self.ce_user)
        resp = self._post_note(
            self.target_foreign, 'ce note on any admin', url=self.ce_url)
        self.assertNotEqual(resp.status_code, 403)
        self.assertEqual(
            HSAdministratorNote.objects.filter(
                hsadmin=self.target_foreign).count(),
            1,
        )
