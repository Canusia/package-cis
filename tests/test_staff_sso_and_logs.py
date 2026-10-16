"""Staff add/edit: username follows the email, and the SSO question decides
the password. Plus the Login Log and SAML Attributes feeds behind the
/ce/users/ tabs.

The tab tables themselves are tenant config (myce_tenant_configs
login_log_table / saml_log_table); their ORM-path checks live with them.
Here the page is exercised with the configs stubbed or missing, so these
tests hold on any tenant.
"""
import json
import uuid
from types import SimpleNamespace
from unittest import mock

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from django_login_history.models import Login

from cis.forms.user import UserForm

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()


def _form_data(**extra):
    return {
        'first_name': 'New', 'last_name': 'Staff',
        'email': f'{uuid.uuid4().hex[:6]}@Example.com',
        'uses_sso': 'Yes', 'password': '',
        'is_active': 'Yes', 'manage_settings': 'No', 'manage_staff_accounts': 'No',
        'process_campus': [], 'default_campus': '',
        **extra,
    }


class _Base(TestCase):
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
        ce, _ = Group.objects.get_or_create(name='ce')
        Group.objects.get_or_create(name='student')
        cls.manager = User.objects.create_superuser(
            username='sso_mgr@example.com', email='sso_mgr@example.com', password='x',
            first_name='Mona', last_name='Manager')
        cls.manager.groups.add(ce)
        # CE role but no manage_staff_accounts -> can_edit_users is False.
        cls.plain_ce = User.objects.create_user(
            username='sso_plain@example.com', email='sso_plain@example.com', password='x')
        cls.plain_ce.groups.add(ce)


class StaffFormTests(_Base):
    def test_username_is_not_a_field(self):
        self.assertNotIn('username', UserForm().fields)

    def test_sso_is_required(self):
        form = UserForm(_form_data(uses_sso=''))
        self.assertFalse(form.is_valid())
        self.assertIn('uses_sso', form.errors)

    def test_add_without_sso_requires_a_password(self):
        form = UserForm(_form_data(uses_sso='No', password=''))
        self.assertFalse(form.is_valid())
        self.assertIn('password', form.errors)

    def test_edit_without_sso_allows_a_blank_password(self):
        form = UserForm(_form_data(uses_sso='No', password='', email=self.plain_ce.email),
                        record=self.plain_ce)
        self.assertTrue(form.is_valid(), form.errors)

    def test_edit_refuses_an_email_another_account_uses(self):
        form = UserForm(_form_data(email='SSO_MGR@example.com'), record=self.plain_ce)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_edit_refuses_an_email_another_account_has_as_username(self):
        User.objects.create_user(username='taken@example.com', email='other@example.com')
        form = UserForm(_form_data(email='taken@example.com'), record=self.plain_ce)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)


class StaffSaveTests(_Base):
    def _form(self, **extra):
        return SimpleNamespace(cleaned_data={
            **_form_data(**extra), 'email': extra.get('email', 'saved@example.com')})

    def test_add_sets_username_to_the_lowercased_email(self):
        user = User.add_new_staff(self._form(email='Mixed.Case@Example.com'))
        self.assertEqual(user.username, 'mixed.case@example.com')

    def test_add_with_sso_has_no_usable_password(self):
        user = User.add_new_staff(self._form(uses_sso='Yes', password='ignored'))
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.uses_sso)

    def test_add_without_sso_sets_the_password(self):
        user = User.add_new_staff(self._form(uses_sso='No', password='s3cret-pw'))
        self.assertTrue(user.check_password('s3cret-pw'))
        self.assertFalse(user.uses_sso)

    def test_edit_moves_username_to_the_email(self):
        self.plain_ce.update(self._form(email='renamed@example.com', uses_sso='No'))
        self.plain_ce.refresh_from_db()
        self.assertEqual(self.plain_ce.username, 'renamed@example.com')

    def test_edit_with_sso_drops_the_password(self):
        self.plain_ce.update(self._form(email=self.plain_ce.email, uses_sso='Yes'))
        self.plain_ce.refresh_from_db()
        self.assertFalse(self.plain_ce.has_usable_password())

    def test_edit_without_sso_and_blank_password_keeps_the_password(self):
        self.plain_ce.update(self._form(email=self.plain_ce.email, uses_sso='No', password=''))
        self.plain_ce.refresh_from_db()
        self.assertTrue(self.plain_ce.check_password('x'))

    def test_blank_password_counts_as_sso(self):
        user = User.objects.create(username='blank@example.com', email='blank@example.com')
        self.assertEqual(user.password, '')
        self.assertTrue(user.uses_sso)


class StaffPagesTests(_Base):
    def setUp(self):
        self.client.force_login(self.manager)

    def test_detail_presets_sso_from_the_password(self):
        sso = User.objects.create(username='pre@example.com', email='pre@example.com')
        sso.set_unusable_password()
        sso.save()
        resp = self.client.get(reverse('cis:user', args=[sso.pk]))
        self.assertEqual(resp.context['form'].initial['uses_sso'], 'Yes')

        resp = self.client.get(reverse('cis:user', args=[self.plain_ce.pk]))
        self.assertEqual(resp.context['form'].initial['uses_sso'], 'No')

    def test_add_page_renders_the_toggle_and_no_username(self):
        resp = self.client.get(reverse('cis:user_add_new'))
        page = resp.content.decode()
        self.assertIn('id="id_uses_sso"', page)
        self.assertIn("$('#div_id_password').toggle", page)
        self.assertNotIn('id="id_username"', page)

    def test_add_post_creates_an_sso_account(self):
        Group.objects.get_or_create(name='ce')
        resp = self.client.post(reverse('cis:user_add_new'), _form_data(
            email='Post.New@example.com', uses_sso='Yes'))
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(email='Post.New@example.com')
        self.assertEqual(user.username, 'post.new@example.com')
        self.assertFalse(user.has_usable_password())


class LoginLogFeedTests(_Base):
    URL = '/ce/api/user-login-log/?format=datatables&draw=1&start=0&length=50'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.student = User.objects.create_user(
            username='sso_stu@example.com', email='sso_stu@example.com', password='x')
        cls.student.groups.add(Group.objects.get(name='student'))
        for user, ip in ((cls.plain_ce, '10.0.0.1'), (cls.student, '10.0.0.2')):
            Login.objects.create(user=user, ip=ip, user_agent='t', country='', region='',
                                 city='')

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    def test_lists_staff_sign_ins_only(self):
        self.client.force_login(self.manager)
        rows = json.loads(self.client.get(self.URL).content)['data']
        self.assertEqual([r['ip'] for r in rows], ['10.0.0.1'])
        self.assertEqual(rows[0]['user']['email'], 'sso_plain@example.com')
        self.assertIn('date', rows[0])

    def test_empty_without_can_edit_users(self):
        self.client.force_login(self.plain_ce)
        self.assertEqual(json.loads(self.client.get(self.URL).content)['data'], [])


class SamlLogFeedTests(_Base):
    URL = '/ce/api/user-saml-log/?format=datatables&draw=1&start=0&length=50'

    def setUp(self):
        if not apps.is_installed('sp'):
            self.skipTest('sp app not installed on this tenant')
        IdP = apps.get_model('sp', 'IdP')
        IdPAttributeLog = apps.get_model('sp', 'IdPAttributeLog')
        idp = IdP.objects.create(name='Test IdP', contact_name='x', contact_email='x@example.com')
        IdPAttributeLog.objects.create(
            idp=idp, nameid='someone@example.com',
            attributes={'email': ['someone@example.com'], 'note': ['<b>x</b>']})
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    def test_lists_logged_attributes(self):
        self.client.force_login(self.manager)
        rows = json.loads(self.client.get(self.URL).content)['data']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['idp_name'], 'Test IdP')
        self.assertEqual(rows[0]['nameid'], 'someone@example.com')
        self.assertEqual(json.loads(rows[0]['attributes'])['email'], ['someone@example.com'])

    def test_empty_without_can_edit_users(self):
        self.client.force_login(self.plain_ce)
        self.assertEqual(json.loads(self.client.get(self.URL).content)['data'], [])


class UsersPageLogTabsTests(_Base):
    def get_page(self, get_table_config):
        self.client.force_login(self.manager)
        with mock.patch('cis.views.users.get_table_config', get_table_config):
            return self.client.get(reverse('cis:users'))

    def test_tabs_rendered_and_wired_when_the_tenant_ships_the_configs(self):
        from cis.services.table_configs import get_table_config
        calls = {}

        def stub(name):
            if name not in ('login_log_table', 'saml_log_table'):
                return get_table_config(name)

            def build_config(**kwargs):
                calls[name] = kwargs
                return {'partial_template': 'cis/messages.html'}
            return SimpleNamespace(build_config=build_config)

        page = self.get_page(stub).content.decode()
        self.assertIn('href="#login_log"', page)
        self.assertEqual(calls['login_log_table'], {
            'variant': 'login_log_index',
            'api_url': '/ce/api/user-login-log?format=datatables'})
        if apps.is_installed('sp'):
            self.assertIn('href="#saml_log"', page)
            self.assertEqual(calls['saml_log_table'], {
                'variant': 'saml_log_index',
                'api_url': '/ce/api/user-saml-log?format=datatables'})

    def test_page_renders_without_the_tabs_when_the_configs_are_missing(self):
        from cis.services.table_configs import get_table_config

        def missing(name):
            if name in ('login_log_table', 'saml_log_table'):
                raise ModuleNotFoundError(
                    name, name=f'{settings.TABLE_CONFIGS_APP}.services.{name}')
            return get_table_config(name)

        resp = self.get_page(missing)
        self.assertEqual(resp.status_code, 200)
        page = resp.content.decode()
        self.assertNotIn('href="#login_log"', page)
        self.assertNotIn('href="#saml_log"', page)
        self.assertIn('id="users_filter"', page)

    @override_settings(TABLE_CONFIGS_APP='cis')
    def test_system_checks_when_the_modules_are_missing(self):
        from cis.checks import login_log_table_check, saml_log_table_check

        self.assertEqual([w.id for w in login_log_table_check(None)], ['cis.W007'])
        expected = ['cis.W008'] if apps.is_installed('sp') else []
        self.assertEqual([w.id for w in saml_log_table_check(None)], expected)
