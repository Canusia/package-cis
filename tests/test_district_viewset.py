from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

from rest_framework.test import APIClient

from cis.models.district import District
from cis.models.highschool import HighSchool

User = get_user_model()


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class DistrictViewSetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='instructor')
        Group.objects.get_or_create(name='ce')
        cls.staff = User.objects.create_user(
            username='staff_d', email='staff_d@example.com',
            password='x', first_name='S', last_name='D', is_staff=True,
        )
        cls.staff.groups.add(Group.objects.get(name='ce'))

        cls.dist_a = District.objects.create(
            name='Alpha District', address1='100 A St',
            city='Aville', state='AS', postal_code='10000',
            primary_phone='555-0001', status='Active',
        )
        cls.dist_b = District.objects.create(name='Beta District', status='Active')
        # Attach 2 highschools to dist_a, 0 to dist_b
        HighSchool.objects.create(name='Alpha HS 1', district=cls.dist_a)
        HighSchool.objects.create(name='Alpha HS 2', district=cls.dist_a)

    def setUp(self):
        self.client = APIClient()
        self._saved = _disconnect_login_signal()
        self.client.force_login(self.staff)

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def test_lists_all_districts(self):
        resp = self.client.get('/ce/api/district/?format=json')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        records = payload.get('results', payload)
        names = {r['name'] for r in records}
        self.assertEqual(names, {'Alpha District', 'Beta District'})

    def test_serializer_includes_table_fields(self):
        resp = self.client.get('/ce/api/district/?format=json')
        records = resp.json().get('results', resp.json())
        a = next(r for r in records if r['name'] == 'Alpha District')
        for field in ('address1', 'city', 'state', 'primary_phone',
                      'num_highschools'):
            self.assertIn(field, a)
        self.assertEqual(a['num_highschools'], 2)
