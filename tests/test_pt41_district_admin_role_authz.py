"""PT-41: cis.views.district_administrator.add_new_role
(model=districtadministratorrole) must be callable only by CIS (CE) staff;
everyone else gets a JSON 403 and no district selector dataset is disclosed.

EWU specifics this test pins down:
- /ce/add_new_ajax/ (reverse 'cis:add_new_ajax') is NOT URL-gated to CE, and
- /highschool_admin/ajax/ (reverse 'highschool_admin:ajax') is gated to the
  highschool_admin role and delegates to the same add_new dispatcher.
So the per-branch user_has_cis_role guard is the SOLE authorization for this
operation. These tests drive both real URLs and cover GET (the dataset-
disclosure path the pentest used) and POST (role creation).
"""
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
from cis.models.district import (
    District,
    DistrictPosition,
    DistrictAdministrator,
    DistrictAdministratorPosition,
)

User = get_user_model()


class DistrictAdminRoleAuthorizationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler blows up in tests
        # because the request has no usable IP. Disconnect for the duration
        # of this test case.
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    @classmethod
    def setUpTestData(cls):
        for name in ('ce', 'highschool_admin', 'district_admin'):
            Group.objects.get_or_create(name=name)

        cls.ce_url = reverse('cis:add_new_ajax')
        cls.hsa_url = reverse('highschool_admin:ajax')

        # Reference data the form's selectors expose. The 'secret' district name
        # is what a non-CE caller must NOT be able to read back.
        cls.district = District.objects.create(name='Secret District 9001')
        cls.position = DistrictPosition.objects.create(name='Superintendent')

        # A district administrator (parent of the role record).
        admin_user = User.objects.create_user(
            username='dadmin_pt41', email='dadmin_pt41@example.com',
            password='x', first_name='Dee', last_name='Admin',
        )
        cls.district_admin = DistrictAdministrator.objects.create(user=admin_user)

        # CE administrator (the only role allowed to reach the handler).
        ce = User.objects.create_user(
            username='ce_pt41', email='ce_pt41@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce

        # Highschool admin — the role used in the pentest exploit.
        hsa = User.objects.create_user(
            username='hsa_pt41', email='hsa_pt41@example.com', password='x',
            first_name='Hank', last_name='Admin',
        )
        hsa.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')

    def _login_verified(self, user):
        """force_login + mark the client session two-step-verified, so the
        request passes the PT-19 verification_required gate on
        /highschool_admin/ajax/ and reaches the per-branch CIS-role 403."""
        self.client.force_login(user)
        session_key = self.client.session.session_key
        TwoStep.objects.update_or_create(
            session_id=session_key,
            user=user,
            defaults={'verification_code': '123456', 'verified': True},
        )

    def _create_payload(self):
        return {
            'model': 'districtadministratorrole',
            'id': '-1',
            'ajax': '1',
            'parent': str(self.district_admin.id),
            'district_admin': str(self.district_admin.id),
            'district': str(self.district.id),
            'position': str(self.position.id),
            'status': 'Active',
        }

    def test_highschool_admin_post_is_403_no_record(self):
        # POST a fully valid create as a highschool_admin via the gated
        # /highschool_admin/ajax/ route. The per-branch guard must short-circuit
        # with 403 BEFORE the form is processed, so nothing is created.
        self._login_verified(self.hsadmin_user)
        resp = self.client.post(self.hsa_url, self._create_payload())
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(DistrictAdministratorPosition.objects.count(), 0)

    def test_highschool_admin_get_is_403_no_disclosure(self):
        # GET the role form as a highschool_admin via /ce/add_new_ajax/ (the
        # exact route + params from the pentest). The GET path must be CE-only,
        # so this returns 403 and the district name/UUID must NOT appear in the
        # response body.
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(self.ce_url, {
            'model': 'districtadministratorrole',
            'ajax': '1',
            'id': '-1',
            'parent': str(self.district_admin.id),
        })
        self.assertEqual(resp.status_code, 403)
        body = resp.content.decode()
        self.assertNotIn('Secret District 9001', body)
        self.assertNotIn(str(self.district.id), body)

    def test_ce_user_get_renders_form(self):
        # A CE user GETting the role form via /ce/add_new_ajax/ is admitted
        # (200) and DOES see the district selector dataset.
        self.client.force_login(self.ce_user)
        resp = self.client.get(self.ce_url, {
            'model': 'districtadministratorrole',
            'ajax': '1',
            'id': '-1',
            'parent': str(self.district_admin.id),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Secret District 9001', resp.content.decode())

    def test_ce_user_can_create_role(self):
        # A CE user posting a valid create via /ce/add_new_ajax/ succeeds and
        # the role record is created.
        self.client.force_login(self.ce_user)
        resp = self.client.post(self.ce_url, self._create_payload())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'success')
        self.assertEqual(
            DistrictAdministratorPosition.objects.filter(
                district_admin=self.district_admin,
                district=self.district,
                position=self.position,
            ).count(),
            1,
        )
