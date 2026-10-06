"""package-cis#64: change history must never store or show a user's password
hash or SSN, and a sign-in must not add a user history row."""
import json
import uuid
from types import SimpleNamespace

from django.contrib.auth.models import Group, update_last_login
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase

from cis.models.customuser import CustomUser
from cis.models.student import Student
from cis.serializers.history import HistorySerializer, SENSITIVE_HISTORY_FIELDS

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:
    _login_history_post_login = None


def _make_user(**extra):
    tag = uuid.uuid4().hex[:8]
    return CustomUser.objects.create_user(
        username=f'h64-{tag}', email=f'h64-{tag}@example.com',
        password='Original-pass-1', **extra)


class UserHistoryModelTests(TestCase):

    def test_history_table_has_no_sensitive_columns(self):
        names = {f.name for f in CustomUser.history.model._meta.fields}
        for field in ('password', 'ssn', 'last_login'):
            self.assertNotIn(field, names)

    def test_last_login_update_creates_no_history_row(self):
        user = _make_user()
        before = CustomUser.history.filter(id=user.pk).count()
        update_last_login(None, user)
        user.refresh_from_db()
        self.assertIsNotNone(user.last_login)
        self.assertEqual(CustomUser.history.filter(id=user.pk).count(), before)

    def test_tracked_field_change_still_creates_history_row(self):
        user = _make_user(first_name='Ann')
        before = CustomUser.history.filter(id=user.pk).count()
        user.first_name = 'Anne'
        user.save()
        self.assertEqual(CustomUser.history.filter(id=user.pk).count(), before + 1)

    def test_password_change_stores_no_hash(self):
        user = _make_user()
        user.set_password('Changed-pass-2')
        user.save()
        for rec in CustomUser.history.filter(id=user.pk):
            self.assertNotIn('password', rec.__dict__)


class HistorySerializerDenylistTests(TestCase):

    def test_get_changes_hides_denylisted_fields(self):
        changes = [
            SimpleNamespace(field='first_name', old='Ann', new='Anne'),
            SimpleNamespace(field='ssn', old='111-22-3333', new='444-55-6666'),
            SimpleNamespace(field='password', old='pbkdf2$old', new='pbkdf2$new'),
            SimpleNamespace(field='last_login', old='a', new='b'),
        ]
        prev = object()
        obj = SimpleNamespace(
            history_type='~', prev_record=prev,
            diff_against=lambda p, excluded_fields=None: SimpleNamespace(changes=changes))
        out = HistorySerializer().get_changes(obj)
        self.assertIn('first_name', out)
        for secret in ('ssn', '111-22-3333', '444-55-6666', 'password',
                       'pbkdf2$', 'last_login'):
            self.assertNotIn(secret, out)

    def test_get_changes_passes_denylist_to_diff(self):
        seen = {}

        def diff_against(prev, excluded_fields=None):
            seen['excluded'] = set(excluded_fields or ())
            return SimpleNamespace(changes=[])

        obj = SimpleNamespace(history_type='~', prev_record=object(),
                              diff_against=diff_against)
        HistorySerializer().get_changes(obj)
        self.assertTrue(SENSITIVE_HISTORY_FIELDS <= seen['excluded'])

    def test_get_value_hides_denylisted_fields(self):
        obj = SimpleNamespace(
            first_name='Ann', password='pbkdf2$hash', ssn='111-22-3333',
            last_login='2026-01-01', history_id=1)
        value = json.loads(HistorySerializer().get_value(obj))
        self.assertEqual(value['first_name'], 'Ann')
        for field in SENSITIVE_HISTORY_FIELDS:
            self.assertNotIn(field, value)


class StudentHistoryEndpointTests(TestCase):

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
        Group.objects.get_or_create(name='student')
        ce, _ = Group.objects.get_or_create(name='ce')
        cls.admin = CustomUser.objects.create_superuser(
            username='h64_admin', email='h64_admin@example.com', password='x')
        cls.admin.groups.add(ce)

    def test_serialized_user_history_never_contains_password_or_ssn(self):
        user = _make_user(first_name='Ann', ssn='111-22-3333')
        student = Student.objects.create(user=user)
        user.ssn = '444-55-6666'
        user.set_password('Changed-pass-2')
        user.first_name = 'Anne'
        user.save()
        update_last_login(None, user)

        self.client.force_login(self.admin)
        resp = self.client.get('/ce/api/student-history/',
                               {'student_id': str(student.id)})
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for secret in ('111-22-3333', '444-55-6666', user.password):
            self.assertNotIn(secret, body)

        user_rows = [r for r in resp.json()['data'] if r['source_model'] == 'User']
        self.assertTrue(user_rows)
        self.assertTrue(any('first_name' in r['changes'] for r in user_rows))
        for row in user_rows:
            value = json.loads(row['value'])
            for field in SENSITIVE_HISTORY_FIELDS:
                self.assertNotIn(field, value)
                self.assertNotIn(f'{field}:', row['changes'])
