"""Staff user form: a CE staff member may only grant the campuses they can
edit themselves (#59 process_campuses).

The add-new and edit pages (/ce/user/add_new, /ce/user/<id>) share UserForm,
which used to offer every prefixed campus to everyone. Editing a colleague who
also belongs to a campus the editor cannot manage must keep that membership
and their existing default campus rather than silently drop or reject them.
"""
import uuid
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from cis.forms.user import UserForm
from cis.models.course import Campus

User = get_user_model()


def _campus(name):
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')


def _staff(campuses, default=None, **extra):
    user = User.objects.create(
        username=f'staff-{uuid.uuid4().hex[:6]}',
        email=f'{uuid.uuid4().hex[:6]}@example.com',
        campus={'manage_staff_accounts': 'Yes',
                'default_campus': str(default.id) if default else ''},
        **extra)
    user.groups.add(Group.objects.get_or_create(name='ce')[0])
    user.set_process_campuses(campuses)
    return user


def _post(campuses, default=None, **extra):
    return {
        'first_name': 'New', 'last_name': 'Staff',
        'email': f'{uuid.uuid4().hex[:6]}@example.com',
        'username': f'new-{uuid.uuid4().hex[:6]}',
        'is_active': 'Yes', 'manage_settings': 'No', 'manage_staff_accounts': 'No',
        'process_campus': [str(c.id) for c in campuses],
        'default_campus': str(default.id) if default else '',
        **extra,
    }


def _ids(choices):
    return {str(value) for value, _ in choices if value != ''}


class UserFormCampusChoicesTests(TestCase):
    def setUp(self):
        self.a, self.b = _campus('A'), _campus('B')
        self.editor = _staff([self.b], default=self.b)

    def test_staff_see_only_their_own_campuses(self):
        form = UserForm(user=self.editor)
        self.assertEqual(_ids(form.fields['process_campus'].choices), {str(self.b.id)})
        self.assertEqual(_ids(form.fields['default_campus'].choices), {str(self.b.id)})

    def test_superuser_sees_every_campus(self):
        root = User.objects.create(username=f'root-{uuid.uuid4().hex[:6]}', is_superuser=True)
        form = UserForm(user=root)
        self.assertLessEqual({str(self.a.id), str(self.b.id)},
                             _ids(form.fields['process_campus'].choices))

    def test_granting_a_campus_the_editor_cannot_edit_is_rejected(self):
        form = UserForm(_post([self.a], default=self.a), user=self.editor)
        self.assertFalse(form.is_valid())
        self.assertIn('process_campus', form.errors)
        self.assertIn('default_campus', form.errors)


class UserFormEditKeepsOtherCampusesTests(TestCase):
    """Editing a colleague who also works on a campus the editor can't manage."""

    def setUp(self):
        self.a, self.b = _campus('A'), _campus('B')
        self.editor = _staff([self.b], default=self.b)
        self.colleague = _staff([self.a, self.b], default=self.a)

    def test_other_campus_membership_is_kept_on_save(self):
        form = UserForm(_post([self.b], default=self.a), user=self.editor, record=self.colleague)
        self.assertTrue(form.is_valid(), form.errors)
        self.colleague.update(form)
        self.assertEqual(set(self.colleague.process_campuses.all()), {self.a, self.b})

    def test_existing_default_campus_is_offered_and_kept(self):
        form = UserForm(user=self.editor, record=self.colleague)
        self.assertIn(str(self.a.id), _ids(form.fields['default_campus'].choices))
        self.assertNotIn(str(self.a.id), _ids(form.fields['process_campus'].choices))

    def test_unticking_the_editors_campus_leaves_only_the_other(self):
        form = UserForm(_post([], default=self.a), user=self.editor, record=self.colleague)
        self.assertTrue(form.is_valid(), form.errors)
        self.colleague.update(form)
        self.assertEqual(list(self.colleague.process_campuses.all()), [self.a])


class UserViewsPassTheEditorTests(TestCase):
    """The add-new and edit pages build the form for the logged-in user."""

    def setUp(self):
        self.a, self.b = _campus('A'), _campus('B')
        self.editor = _staff([self.b], default=self.b)

    def _form(self, view, *args):
        from cis.views import users as user_views
        request = RequestFactory().get('/')
        request.user = self.editor
        with mock.patch.object(user_views, 'render', return_value=HttpResponse()) as render, \
                mock.patch.object(user_views, 'draw_menu', return_value=''):
            view(request, *args)
        return render.call_args.args[2]['form']

    def test_add_new_offers_only_the_editors_campuses(self):
        from cis.views.users import add_new
        form = self._form(add_new)
        self.assertEqual(_ids(form.fields['process_campus'].choices), {str(self.b.id)})

    def test_edit_offers_only_the_editors_campuses(self):
        from cis.views.users import detail
        colleague = _staff([self.b])
        form = self._form(detail, colleague.id)
        self.assertEqual(_ids(form.fields['process_campus'].choices), {str(self.b.id)})


class AddNewExistingUsernameTests(TestCase):
    """Add-new with a username that already exists must not overwrite that
    account (name, email, password, permissions, default campus) -- it only
    adds the submitted campuses to the ones the account already has."""

    def setUp(self):
        self.a, self.b = _campus('A'), _campus('B')
        self.editor = _staff([self.b], default=self.b)

    def _post(self, data):
        from cis.views import users as user_views
        request = RequestFactory().post('/', data)
        request.user = self.editor
        with mock.patch.object(user_views, 'render', return_value=HttpResponse()) as render, \
                mock.patch.object(user_views, 'draw_menu', return_value=''), \
                mock.patch.object(user_views.messages, 'add_message'):
            response = user_views.add_new(request)
        return response, render

    def test_existing_staff_only_gains_the_new_campus(self):
        existing = _staff([self.a], default=self.a, first_name='Orig', last_name='Name')
        existing.set_password('original-pw')
        existing.save()
        before = User.objects.count()

        response, _ = self._post(_post(
            [self.b], default=self.b, username=existing.username.upper(),
            first_name='Hijack', email='hijack@example.com',
            password='new-pw', manage_staff_accounts='Yes', manage_settings='Yes'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.count(), before)
        existing.refresh_from_db()
        self.assertEqual(set(existing.process_campuses.all()), {self.a, self.b})
        self.assertEqual(existing.first_name, 'Orig')
        self.assertNotEqual(existing.email, 'hijack@example.com')
        self.assertTrue(existing.check_password('original-pw'))
        self.assertEqual(existing.campus.get('default_campus'), str(self.a.id))
        self.assertEqual(existing.campus.get('manage_staff_accounts'), 'Yes')  # from _staff, unchanged
        self.assertNotEqual(existing.campus.get('manage_settings'), 'Yes')

    def test_existing_non_staff_account_is_refused(self):
        student = User.objects.create(
            username=f'stu-{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@example.com')

        response, render = self._post(_post([self.b], default=self.b, username=student.username))

        self.assertEqual(response.status_code, 200)  # form re-rendered with an error
        self.assertIn('username', render.call_args.args[2]['form'].errors)
        student.refresh_from_db()
        self.assertEqual(list(student.process_campuses.all()), [])
        self.assertFalse(student.groups.filter(name='ce').exists())

    def test_new_username_still_creates_the_account(self):
        data = _post([self.b], default=self.b)
        response, _ = self._post(data)
        self.assertEqual(response.status_code, 302)
        created = User.objects.get(username=data['username'])
        self.assertEqual(list(created.process_campuses.all()), [self.b])
        self.assertTrue(created.groups.filter(name='ce').exists())
