"""#45 follow-up: the CE Document Types page, and the two readers that move to it.

Pinned here:
  - the list, the edit page and the form's campus field are all campus-scoped;
  - `code` is fixed once a type exists, and a code that would shadow a legacy
    unassigned (null-campus) type is refused;
  - the page still renders for a tenant whose myce_tenant_configs lacks the
    table module (a missing module must not take down the URLconf);
  - the student upload dropdown reads DocumentType, falling back to
    support_docs.types only on a tenant that has never seeded;
  - support_docs.types turns read-only once DocumentType has rows -- and a
    save of the setting then keeps the stored list rather than wiping it;
  - the Document Types menu migration is idempotent and reversible.
"""
import importlib
import json
import uuid
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import RequestFactory, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from cis.models.course import Campus, DocumentType
from cis.models.settings import Setting
from cis.models.term import AcademicYear, Term

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


def _campus(name):
    return Campus.objects.create(
        name=f'{name}-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')


class _CEUserMixin:
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

    def make_ce(self, *campuses):
        user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@example.com',
            password='x', is_staff=True)
        user.groups.add(Group.objects.get_or_create(name='ce')[0])
        user.campus = {'process_campus': [str(c.id) for c in campuses]}
        user.save()
        return user


class DocumentTypePageTests(_CEUserMixin, TestCase):
    def setUp(self):
        self.campus_a = _campus('A')
        self.campus_b = _campus('B')
        self.type_a = DocumentType.objects.create(
            code='transcript', label='HS Transcript', campus=self.campus_a)
        self.type_b = DocumentType.objects.create(
            code='transcript', label='Transcript', campus=self.campus_b)
        self.unassigned = DocumentType.objects.create(
            code='legacy', label='Legacy Type')

        self.ce = self.make_ce(self.campus_a)
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.ce)

    def test_feed_is_scoped_to_the_users_campuses(self):
        resp = self.client.get('/ce/api/document-type/?format=datatables'
                               '&draw=1&start=0&length=50')
        self.assertEqual(resp.status_code, 200)
        ids = {row['id'] for row in resp.json()['data']}
        self.assertEqual(ids, {str(self.type_a.id), str(self.unassigned.id)})

    def test_index_renders(self):
        resp = self.client.get(reverse('cis:document_types'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Document Types')

    def test_index_renders_without_the_table_module(self):
        """A tenant lagging on myce_tenant_configs gets a plain list."""
        with mock.patch('cis.views.document_type.get_table_config',
                        side_effect=ImportError('no document_types_table')):
            resp = self.client.get(reverse('cis:document_types'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'HS Transcript')
        # The fallback list is campus-scoped too.
        self.assertNotIn(str(self.type_b.id), resp.content.decode())

    def test_edit_page_for_own_campus(self):
        resp = self.client.get(reverse('cis:document_type', args=[self.type_a.id]))
        self.assertEqual(resp.status_code, 200)

    def test_edit_page_for_other_campus_refused(self):
        resp = self.client.get(reverse('cis:document_type', args=[self.type_b.id]))
        self.assertEqual(resp.status_code, 403)

    def test_edit_saves_label_and_status_but_not_code(self):
        resp = self.client.post(
            reverse('cis:document_type', args=[self.type_a.id]), {
                'label': 'High School Transcript', 'code': 'renamed',
                'campus': self.campus_a.id, 'status': 'Inactive',
            })
        self.assertEqual(resp.status_code, 302)
        self.type_a.refresh_from_db()
        self.assertEqual(self.type_a.label, 'High School Transcript')
        self.assertEqual(self.type_a.status, 'Inactive')
        self.assertEqual(self.type_a.code, 'transcript')

    def test_add_new_creates_type(self):
        resp = self.client.post(reverse('cis:document_type_add_new'), {
            'label': 'TSI Assessment', 'code': 'tsi',
            'campus': self.campus_a.id, 'status': 'Active',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(DocumentType.objects.filter(
            code='tsi', campus=self.campus_a).exists())

    def test_add_new_refuses_another_users_campus(self):
        resp = self.client.post(reverse('cis:document_type_add_new'), {
            'label': 'TSI Assessment', 'code': 'tsi',
            'campus': self.campus_b.id, 'status': 'Active',
        })
        self.assertEqual(resp.status_code, 200)  # re-rendered with errors
        self.assertFalse(DocumentType.objects.filter(code='tsi').exists())


class DocumentTypeFormTests(_CEUserMixin, TestCase):
    def setUp(self):
        self.campus_a = _campus('A')
        self.campus_b = _campus('B')
        self.ce = self.make_ce(self.campus_a)

    def _form(self, data, instance=None):
        from cis.forms.course import DocumentTypeForm
        return DocumentTypeForm(data, instance=instance, user=self.ce)

    def test_campus_required(self):
        form = self._form({'label': 'X', 'code': 'x', 'status': 'Active'})
        self.assertFalse(form.is_valid())
        self.assertIn('campus', form.errors)

    def test_campus_choices_limited_to_the_users_campuses(self):
        form = self._form({})
        self.assertEqual(
            list(form.fields['campus'].queryset), [self.campus_a])

    def test_code_shadowing_an_unassigned_type_refused(self):
        DocumentType.objects.create(code='legacy', label='Legacy')
        form = self._form({'label': 'Mine', 'code': 'Legacy',
                           'campus': self.campus_a.id, 'status': 'Active'})
        self.assertFalse(form.is_valid())
        self.assertIn('code', form.errors)

    def test_duplicate_code_in_same_campus_refused(self):
        DocumentType.objects.create(
            code='tsi', label='TSI', campus=self.campus_a)
        form = self._form({'label': 'Other', 'code': 'TSI',
                           'campus': self.campus_a.id, 'status': 'Active'})
        self.assertFalse(form.is_valid())
        self.assertIn('code', form.errors)

    def test_legacy_type_can_be_given_a_campus(self):
        legacy = DocumentType.objects.create(code='legacy', label='Legacy')
        form = self._form({'label': 'Legacy', 'code': 'legacy',
                           'campus': self.campus_a.id, 'status': 'Active'},
                          instance=legacy)
        self.assertTrue(form.is_valid(), form.errors)


class UploadDropdownTests(TestCase):
    def setUp(self):
        self.campus_a = _campus('A')
        self.campus_b = _campus('B')
        academic_year = AcademicYear.objects.create(
            name=f'AY{_sfx()}', campus=self.campus_a)
        self.term = Term.objects.create(
            academic_year=academic_year, code=f'T{_sfx()}', label=f'L{_sfx()}')
        Setting.objects.update_or_create(
            key='cis.settings.support_docs',
            defaults={'value': {'types': ['Old Setting Type']}})

    def _choices(self):
        from cis.forms.student import StudentSupportingDocumentForm
        form = StudentSupportingDocumentForm(
            SimpleNamespace(id=uuid.uuid4()), term=self.term)
        return [value for value, _ in form.fields['document_type'].choices]

    def test_falls_back_to_setting_when_never_seeded(self):
        self.assertEqual(self._choices(), ['', 'Old Setting Type'])

    def test_reads_active_types_for_the_terms_campus(self):
        DocumentType.objects.create(code='t', label='HS Transcript',
                                    campus=self.campus_a)
        DocumentType.objects.create(code='u', label='Unassigned Type')
        DocumentType.objects.create(code='r', label='Retired',
                                    campus=self.campus_a, status='Inactive')
        DocumentType.objects.create(code='o', label='Other Campus',
                                    campus=self.campus_b)
        self.assertEqual(
            self._choices(), ['', 'HS Transcript', 'Unassigned Type'])

    def test_same_label_listed_once(self):
        DocumentType.objects.create(code='t', label='Transcript',
                                    campus=self.campus_a)
        DocumentType.objects.create(code='t2', label='transcript')
        self.assertEqual(self._choices(), ['', 'Transcript'])


class SupportDocsTypesReadOnlyTests(TestCase):
    def _form(self, data=None):
        from cis.settings.support_docs import support_docs
        request = RequestFactory().get('/?report_id=x')
        return support_docs(request, data) if data is not None \
            else support_docs(request)

    def setUp(self):
        Setting.objects.update_or_create(
            key='cis.settings.support_docs',
            defaults={'value': {'types': ['Transcript', 'Waiver']}})

    def test_editable_when_never_seeded(self):
        self.assertFalse(self._form().fields['types'].disabled)

    def test_read_only_once_seeded_and_save_keeps_stored_types(self):
        from cis.settings.support_docs import support_docs
        DocumentType.objects.create(code='t', label='Transcript')
        self.assertTrue(self._form().fields['types'].disabled)

        # The settings app posts without `initial`; a disabled field must not
        # save as blank.
        form = self._form({'types': 'Tampered', 'email_enabled': 'No'})
        self.assertTrue(form.is_valid(), form.errors)
        form.run_record()
        self.assertEqual(support_docs.get_types(), ['Transcript', 'Waiver'])


class DocumentTypesMenuMigrationTests(TestCase):
    def setUp(self):
        self.mod = importlib.import_module(
            'cis.migrations.0084_add_document_types_nav')

    def _value(self):
        return {'ce_menu': json.dumps([{
            'name': 'classes', 'sub_menu': [
                {'name': 'courses'}, {'name': 'cohorts'},
                {'type': 'separator'}, {'name': 'academic_years'},
            ]}])}

    def _names(self, value):
        items = json.loads(value['ce_menu'])
        return [s.get('name') for s in items[0]['sub_menu']]

    def test_inserted_after_subjects_once(self):
        value = self.mod._patch_menu(self._value())
        value = self.mod._patch_menu(value)
        self.assertEqual(
            self._names(value),
            ['courses', 'cohorts', 'document_types', None, 'academic_years'])

    def test_reverse_removes_it(self):
        value = self.mod._patch_menu(self._value())
        value = self.mod._patch_menu(value, remove=True)
        self.assertNotIn('document_types', self._names(value))

    def test_missing_parent_left_untouched(self):
        value = {'ce_menu': json.dumps([{'name': 'users', 'sub_menu': []}])}
        self.assertEqual(self.mod._patch_menu(dict(value)), value)


class DocumentTypesTableCheckTests(TestCase):
    """cis.W002: v0.0.42 expects the tenant to ship document_types_table."""

    def test_no_warning_when_tenant_ships_the_module(self):
        from cis.checks import document_types_table_check
        self.assertEqual(document_types_table_check(None), [])

    def test_warns_when_module_missing(self):
        from cis.checks import document_types_table_check
        with mock.patch('cis.checks.importlib.util.find_spec', return_value=None):
            warnings = document_types_table_check(None)
        self.assertEqual([w.id for w in warnings], ['cis.W002'])

    def test_warns_when_table_configs_app_missing(self):
        from cis.checks import document_types_table_check
        with mock.patch('cis.checks.importlib.util.find_spec',
                        side_effect=ModuleNotFoundError('nope')):
            warnings = document_types_table_check(None)
        self.assertEqual([w.id for w in warnings], ['cis.W002'])
