"""CE-API viewset authorization sweep (PT-43/PT-44 defect class).

CourseViewSet, CohortViewSet, LocationViewSet, and TechCenterViewSet shipped
with no permission_classes, so any authenticated user (e.g. highschool_admin)
could read CE-only data. Each must be CIS-only: highschool_admin -> 403,
ce -> 200. (ClassSectionViewSet is intentionally open via get_queryset role
scoping and is NOT part of this sweep.)
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from rest_framework.test import APIClient

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

ENDPOINTS = [
    '/ce/api/course/',
    '/ce/api/cohort/',
    '/ce/api/location/',
    '/ce/api/tech_center/',
]


class CeApiAuthzSweepTests(TestCase):
    @classmethod
    def setUpClass(cls):
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

        ce = User.objects.create_user(
            username='ce_sweep', email='ce_sweep@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce

        hsa = User.objects.create_user(
            username='hsa_sweep', email='hsa_sweep@example.com', password='x',
            first_name='Hank', last_name='Admin',
        )
        hsa.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    def test_highschool_admin_forbidden_on_all(self):
        self.client.force_login(self.hsadmin_user)
        for ep in ENDPOINTS:
            resp = self.client.get(ep + '?format=json')
            self.assertEqual(
                resp.status_code, 403,
                msg=f'{ep} should be 403 for highschool_admin, got {resp.status_code}')

    def test_ce_allowed_on_all(self):
        self.client.force_login(self.ce_user)
        for ep in ENDPOINTS:
            resp = self.client.get(ep + '?format=json')
            self.assertEqual(
                resp.status_code, 200,
                msg=f'{ep} should be 200 for ce, got {resp.status_code}')
