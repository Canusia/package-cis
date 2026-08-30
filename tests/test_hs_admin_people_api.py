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


from django.urls import reverse


class HsAdminIndexTabsTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.url = reverse('cis:hs_admins')

    def tearDown(self):
        self.tear_down_fixture()

    def test_both_tabs_render(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('href="#all"', body)
        self.assertIn('href="#people"', body)
        self.assertIn('records_all', body)
        self.assertIn('records_people', body)

    def test_people_tab_points_at_the_administrator_api(self):
        body = self.client.get(self.url).content.decode()
        self.assertIn('/ce/api/hs-administrator?format=datatables', body)

    def test_toggle_status_is_replaced_by_edit_status(self):
        body = self.client.get(self.url).content.decode()
        self.assertIn("slug: 'edit_status'", body)
        self.assertNotIn("slug: 'toggle_status'", body)
        self.assertIn("slug: 'toggle_student_recommendation'", body)

    def test_role_tab_bulk_actions(self):
        body = self.client.get(self.url).content.decode()
        for slug in ['edit_status', 'delete', 'toggle_student_recommendation',
                     'change_password', 'password_reset_link']:
            self.assertIn("slug: '%s'" % slug, body)

    def test_people_tab_posts_to_the_person_endpoint(self):
        body = self.client.get(self.url).content.decode()
        self.assertIn(
            reverse('cis:hs_admin_do_person_bulk_action'), body)

    def test_page_loads_the_shared_bulk_helper_not_an_inline_copy(self):
        body = self.client.get(self.url).content.decode()
        self.assertIn('bulk_action.js', body)
        self.assertNotIn('function do_bulk_action(', body)
