"""Status filter on FacultyViewSet (/ce/api/faculty), backing the Status
dropdown added to the All Faculty tab (cis/templates/cis/faculty/index.html).

Deliberately not campus-gated (see the comment on FacultyViewSet.get_queryset)
-- this only covers the `status` GET param.

EWU has no test factories; fixtures follow cis/tests/test_faculty_role_delete.py.
"""
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.faculty import FacultyCoordinator
from cis.tests.test_faculty_role_delete import FacultyRoleFixtureMixin


class FacultyViewSetStatusFilterTests(FacultyRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        # coord_a stays Active (the model default); coord_b becomes Inactive.
        self.coord_b.status = 'Inactive'
        self.coord_b.save()

    def tearDown(self):
        self.tear_down_fixture()

    def _ids(self, query=''):
        resp = self.client.get('/ce/api/faculty/?format=datatables' + query)
        self.assertEqual(resp.status_code, 200)
        return {row['id'] for row in resp.json()['data']}

    def test_no_status_param_returns_all(self):
        ids = self._ids()
        self.assertIn(str(self.coord_a.id), ids)
        self.assertIn(str(self.coord_b.id), ids)

    def test_status_active_narrows_to_active_rows(self):
        ids = self._ids('&status=Active')
        self.assertIn(str(self.coord_a.id), ids)
        self.assertNotIn(str(self.coord_b.id), ids)

    def test_status_inactive_narrows_to_inactive_rows(self):
        ids = self._ids('&status=Inactive')
        self.assertNotIn(str(self.coord_a.id), ids)
        self.assertIn(str(self.coord_b.id), ids)

    def test_status_is_case_insensitive(self):
        ids = self._ids('&status=active')
        self.assertIn(str(self.coord_a.id), ids)
        self.assertNotIn(str(self.coord_b.id), ids)

    def test_status_all_clears_the_filter(self):
        ids = self._ids('&status=all')
        self.assertIn(str(self.coord_a.id), ids)
        self.assertIn(str(self.coord_b.id), ids)

    def test_junk_status_value_narrows_to_nothing_without_raising(self):
        resp = self.client.get('/ce/api/faculty/?format=datatables&status=not-a-real-status')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data'], [])


class FacultyStatusFilterOptionsTests(TestCase):
    """The All Faculty status dropdown is driven by the model.

    It used to hardcode Active/Inactive in the template. A third status added
    to FacultyCoordinator.STATUS_OPTIONS would then have been silently
    unfilterable — present in the data, absent from the dropdown, with nothing
    failing to signal it.
    """

    def setUp(self):
        self._saved = list(user_logged_in.receivers)
        user_logged_in.receivers = []
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.staff = CustomUser.objects.create_superuser(
            username='facstatusopts', email='facstatusopts@example.com', password='x')
        self.staff.groups.add(ce_group)
        self.client.force_login(self.staff)

    def tearDown(self):
        user_logged_in.receivers = self._saved

    def test_every_model_status_is_offered(self):
        body = self.client.get(reverse('cis:faculty_coordinators')).content.decode()
        for value, label in FacultyCoordinator.STATUS_OPTIONS:
            self.assertIn(f'<option value="{value}">{label}</option>', body)

    def test_a_new_model_status_reaches_the_dropdown(self):
        """The discriminating case.

        Asserting only today's Active/Inactive would pass against the old
        hardcoded markup too, since those are exactly the two values it
        spelled out. Adding a third option to the model and requiring it to
        render is what actually proves the dropdown is driven by
        STATUS_OPTIONS rather than by a copy of it.
        """
        extended = list(FacultyCoordinator.STATUS_OPTIONS) + [('Emeritus', 'Emeritus')]
        with patch.object(FacultyCoordinator, 'STATUS_OPTIONS', extended):
            body = self.client.get(reverse('cis:faculty_coordinators')).content.decode()
        self.assertIn('<option value="Emeritus">Emeritus</option>', body)

    def test_an_all_option_clears_the_filter(self):
        body = self.client.get(reverse('cis:faculty_coordinators')).content.decode()
        self.assertIn('<option value="">All</option>', body)
