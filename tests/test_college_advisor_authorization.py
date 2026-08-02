"""PT-21: cis.views.highschool.add_new_college_advisor
(model=highschoolcollegeadvisor) must be callable only by CIS (CE) staff;
everyone else gets a JSON 403.

EWU specifics this test pins down:
- /ce/add_new_ajax/ (reverse 'cis:add_new_ajax') is NOT URL-gated to CE, and
- /highschool_admin/ajax/ (reverse 'highschool_admin:ajax') is gated to the
  highschool_admin role and delegates to the same add_new dispatcher.
So the per-method user_has_cis_role guard is the SOLE authorization for this
operation. These tests drive both real URLs.
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
from cis.models.highschool import HighSchool, HighSchoolCollegeAdvisor

User = get_user_model()


class CollegeAdvisorAuthorizationTests(TestCase):
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
        for name in ('ce', 'highschool_admin'):
            Group.objects.get_or_create(name=name)

        cls.ce_url = reverse('cis:add_new_ajax')
        cls.hsa_url = reverse('highschool_admin:ajax')

        cls.highschool = HighSchool.objects.create(name='Test High')

        # CE administrator (the only role allowed to reach the handler).
        ce = User.objects.create_user(
            username='ce_pt21', email='ce_pt21@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce

        # The advisor must be in the 'ce' group: HSCollegeAdvisorForm.advisor
        # queryset is CustomUser.objects.filter(groups__name='ce').
        advisor = User.objects.create_user(
            username='advisor_pt21', email='advisor_pt21@example.com',
            password='x', first_name='Addy', last_name='Visor',
        )
        advisor.groups.add(Group.objects.get(name='ce'))
        cls.advisor = advisor

        # Highschool admin — the role used in the pentest exploit.
        hsa = User.objects.create_user(
            username='hsa_pt21', email='hsa_pt21@example.com', password='x',
            first_name='Hank', last_name='Admin',
        )
        hsa.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa

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

    def _create_payload(self):
        return {
            'model': 'highschoolcollegeadvisor',
            'id': '-1',
            'ajax': '1',
            'highschool': str(self.highschool.id),
            'advisor': str(self.advisor.id),
            'status': 'Active',
        }

    def test_highschool_admin_post_is_403_no_record(self):
        # POST a fully valid create as a highschool_admin via the gated
        # /highschool_admin/ajax/ route. The per-method guard must short-circuit
        # with 403 BEFORE the form is processed, so nothing is created.
        self._login_verified(self.hsadmin_user)
        resp = self.client.post(self.hsa_url, self._create_payload())
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(HighSchoolCollegeAdvisor.objects.count(), 0)

    def test_highschool_admin_get_is_403_no_disclosure(self):
        # Seed a record (as data, not via the handler), then try to prefill the
        # edit form for it as a highschool_admin. The GET path must also be
        # CE-only, so this returns 403 and discloses nothing.
        record = HighSchoolCollegeAdvisor.objects.create(
            highschool=self.highschool, advisor=self.advisor, status='Active')
        self._login_verified(self.hsadmin_user)
        resp = self.client.get(self.hsa_url, {
            'model': 'highschoolcollegeadvisor',
            'ajax': '1',
            'id': str(record.id),
            'parent': str(self.highschool.id),
        })
        self.assertEqual(resp.status_code, 403)

    def test_ce_user_can_create_advisor(self):
        # A CE user posting a valid create via /ce/add_new_ajax/ succeeds.
        self.client.force_login(self.ce_user)
        resp = self.client.post(self.ce_url, self._create_payload())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'success')
        self.assertEqual(
            HighSchoolCollegeAdvisor.objects.filter(
                highschool=self.highschool, advisor=self.advisor
            ).count(),
            1,
        )
