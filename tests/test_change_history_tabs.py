import uuid
from types import SimpleNamespace

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:
    _login_history_post_login = None


class ChangeHistoryTabWiringTests(TestCase):
    """Each of the three entities registers a change_history tab pointing at
    its history API with the correct (fixed) template + changes column."""

    def test_highschool_tab_context(self):
        from cis.tabs.highschool import change_history_tab
        ctx = change_history_tab(None, SimpleNamespace(id='HS1'))
        self.assertEqual(ctx['history_table_id'], 'highschool_history')
        self.assertEqual(ctx['history_api_url'],
                         '/ce/api/highschool-history/?highschool_id=HS1')

    def test_class_section_tab_context(self):
        from cis.tabs.class_section import change_history_tab
        ctx = change_history_tab(None, SimpleNamespace(id='CS1'))
        self.assertEqual(ctx['history_table_id'], 'class_section_history')
        self.assertEqual(ctx['history_api_url'],
                         '/ce/api/class-section-history/?class_section_id=CS1')

    def test_registration_tab_context(self):
        from cis.tabs.registration import change_history_tab
        ctx = change_history_tab(None, SimpleNamespace(id='R1'))
        self.assertEqual(ctx['history_table_id'], 'registration_history')
        self.assertEqual(ctx['history_api_url'],
                         '/ce/api/registration-history/?registration_id=R1')


class HistorySerializerChangesTests(TestCase):
    def _ser(self):
        from cis.serializers.history import HistorySerializer
        return HistorySerializer()

    def test_changed_row_without_prior_version_shows_label(self):
        # Records that predate history tracking produce a first '~' row with no
        # prev_record — the Changes column must not be blank.
        obj = SimpleNamespace(history_type='~', prev_record=None)
        self.assertEqual(self._ser().get_changes(obj), 'Initial recorded version')

    def test_created_row(self):
        obj = SimpleNamespace(history_type='+', prev_record=None)
        self.assertEqual(self._ser().get_changes(obj), 'Record created')


class HighSchoolHistoryEndpointTests(TestCase):
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
        Group.objects.get_or_create(name='ce')
        cls.admin = CustomUser.objects.create(
            username='ce@x.com', email='ce@x.com', is_active=True, psid='-')
        cls.admin.groups.add(Group.objects.get(name='ce'))

    def setUp(self):
        self.client.force_login(self.admin)

    def test_history_records_field_level_change(self):
        hs = HighSchool.objects.create(name='Old Name', code=f'H{uuid.uuid4().hex[:6]}')
        hs.name = 'New Name'
        hs.save()

        resp = self.client.get('/ce/api/highschool-history/', {'highschool_id': str(hs.id)})
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()['data']
        # Created + Changed = 2 history rows.
        self.assertEqual(len(rows), 2)
        changed = next(r for r in rows if r['history_type'] == 'Changed')
        # The 'changes' field shows what data changed (name old -> new).
        self.assertIn('name', changed['changes'])
        self.assertIn('Old Name', changed['changes'])
        self.assertIn('New Name', changed['changes'])

    def test_unknown_id_returns_empty(self):
        resp = self.client.get('/ce/api/highschool-history/',
                               {'highschool_id': str(uuid.uuid4())})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data'], [])
