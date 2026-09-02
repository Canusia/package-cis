"""Status filter on FacultyViewSet (/ce/api/faculty), backing the Status
dropdown added to the All Faculty tab (cis/templates/cis/faculty/index.html).

Deliberately not campus-gated (see the comment on FacultyViewSet.get_queryset)
-- this only covers the `status` GET param.

EWU has no test factories; fixtures follow cis/tests/test_faculty_role_delete.py.
"""
from django.test import TestCase

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
