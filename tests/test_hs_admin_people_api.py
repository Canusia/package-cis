from django.test import TestCase

from cis.tests.test_hs_admin_roles_tab import HsAdminRoleFixtureMixin


class HsAdministratorPeopleApiTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def _rows(self):
        resp = self.client.get('/ce/api/hs-administrator/?format=datatables')
        self.assertEqual(resp.status_code, 200)
        return {row['id']: row for row in resp.json()['data']}

    def test_one_row_per_administrator(self):
        rows = self._rows()
        self.assertEqual(
            set(rows.keys()),
            {str(self.admin_a.id), str(self.admin_b.id)})

    def test_school_count_counts_roles(self):
        rows = self._rows()
        self.assertEqual(rows[str(self.admin_a.id)]['school_count'], 2)
        self.assertEqual(rows[str(self.admin_b.id)]['school_count'], 1)

    def test_ordering_by_school_count_does_not_500(self):
        """school_count must be a real annotation: DataTables orders server-side
        by the data-name value, and a SerializerMethodField would FieldError."""
        resp = self.client.get(
            '/ce/api/hs-administrator/?format=datatables'
            '&order[0][column]=0&order[0][dir]=desc'
            '&columns[0][data]=school_count&columns[0][name]=school_count'
            '&columns[0][orderable]=true&columns[0][searchable]=false')
        self.assertEqual(resp.status_code, 200)
        counts = [row['school_count'] for row in resp.json()['data']]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_nested_use_of_the_serializer_still_works(self):
        """HSAdministratorSerializer is nested inside
        HighSchoolAdministratorSerializer, where instances carry no
        school_count annotation. The field must be optional there."""
        resp = self.client.get('/ce/api/hs-administrator-position/?format=datatables')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['data']), 3)
