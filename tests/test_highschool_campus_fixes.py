"""Final-review fixes for high school <-> campus links.

C1 importer links, C3 status form, I1 scoped CE endpoints, I2 report and
settings pickers, I5b can_manage_link, I6 merge, and the must-fix minors.
"""
import json
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.http import Http404
from django.test import RequestFactory, TestCase, override_settings

from cis.campus_context import campus_context
from cis.models.course import Campus
from cis.models.highschool import HighSchool, HighSchoolCampus
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition, HSPosition)
from cis.models.note import HighSchoolNote
from cis.signals.staff_campus import set_process_campuses
from cis.views import highschool as views

User = get_user_model()
PREFIX = settings.CAMPUS_CODE_PREFIX


def _sfx():
    return uuid.uuid4().hex[:8]


def _campus(name=None):
    return Campus.objects.create(
        name=name or f'C-{_sfx()}', code=f'{PREFIX}_{_sfx()}')


def _hs(name, **kw):
    kw.setdefault('code', _sfx())
    hs = HighSchool.objects.create(name=name, **kw)
    HighSchoolCampus.objects.filter(highschool=hs).delete()
    HighSchool.objects.filter(pk=hs.pk).update(status=hs.status)
    return hs


def _link(hs, campus, status='Active', code=''):
    return HighSchoolCampus.objects.create(
        highschool=hs, campus=campus, status=status, building_code=code)


def _status(hs):
    return HighSchool.objects.get(pk=hs.pk).status


def _first_campus():
    """A new prefixed campus that deployment_campus() picks (first by name)."""
    campus = _campus('0000-first')
    for c in Campus.objects.filter(code__startswith=PREFIX).exclude(pk=campus.pk):
        Campus.objects.filter(pk=c.pk).update(name=f'zz-{c.name}')
    return campus


def _ce(*campuses):
    Group.objects.get_or_create(name='ce')
    user = User.objects.create_user(
        username=f'ce-{_sfx()}', email=f'{_sfx()}@x.com', password='x')
    user.groups.add(Group.objects.get(name='ce'))
    if campuses:
        set_process_campuses(user, list(campuses))
    return user


def _su():
    Group.objects.get_or_create(name='ce')
    user = User.objects.create_superuser(
        username=f'su-{_sfx()}', email=f'{_sfx()}@x.com', password='x')
    user.groups.add(Group.objects.get(name='ce'))
    return user


def _call(view, user, post=None, get=None, campus=None, **kwargs):
    rf = RequestFactory()
    req = rf.post('/x', post) if post is not None else rf.get('/x', get or {})
    req.user = user
    if campus is None:
        return view(req, **kwargs)
    with campus_context(campus):
        return view(req, **kwargs)


# --- C1: CSV import ---------------------------------------------------------

def _rows(*rows):
    return [dict(r) for r in rows]


@override_settings(MULTI_CAMPUS=False)
class ImportSingleCampusTests(TestCase):
    def setUp(self):
        self.campus = _first_campus()
        self.other = _campus('zz-other')

    def test_bulk_create_links_new_schools_to_deployment_campus(self):
        code_a, code_b = _sfx(), _sfx()
        HighSchool.import_from_csv(_rows(
            {'name': 'New A', 'code': code_a, 'status': 'Active'},
            {'name': 'New B', 'code': code_b, 'status': 'Inactive'},
        ), use_bulk=True)
        a = HighSchool.objects.get(code=code_a)
        b = HighSchool.objects.get(code=code_b)
        self.assertEqual(
            list(a.campus_links.values_list('campus_id', 'status')),
            [(self.campus.pk, 'Active')])
        self.assertEqual(
            list(b.campus_links.values_list('campus_id', 'status')),
            [(self.campus.pk, 'Inactive')])
        self.assertEqual((_status(a), _status(b)), ('Active', 'Inactive'))

    def test_bulk_update_status_lands_on_deployment_campus_link(self):
        hs = _hs('Old', status='Active')
        _link(hs, self.campus, 'Active')
        _link(hs, self.other, 'Inactive')
        HighSchool.import_from_csv(_rows(
            {'name': 'Old', 'code': hs.code, 'status': 'Inactive'}), use_bulk=True)
        self.assertEqual(
            HighSchoolCampus.objects.get(highschool=hs, campus=self.campus).status,
            'Inactive')
        self.assertEqual(
            HighSchoolCampus.objects.get(highschool=hs, campus=self.other).status,
            'Inactive')
        self.assertEqual(_status(hs), 'Inactive')

    def test_bulk_update_status_creates_missing_link(self):
        hs = _hs('Unlinked', status='Active')
        HighSchool.import_from_csv(_rows(
            {'name': 'Unlinked', 'code': hs.code, 'status': 'Inactive'}),
            use_bulk=True)
        link = HighSchoolCampus.objects.get(highschool=hs)
        self.assertEqual((link.campus_id, link.status), (self.campus.pk, 'Inactive'))
        self.assertEqual(_status(hs), 'Inactive')

    def test_bulk_update_without_status_column_leaves_links(self):
        hs = _hs('Keep', status='Active')
        _link(hs, self.campus, 'Inactive')
        _link(hs, self.other, 'Active')
        HighSchool.import_from_csv(_rows(
            {'name': 'Keep renamed', 'code': hs.code}), use_bulk=True)
        self.assertEqual(
            HighSchoolCampus.objects.get(highschool=hs, campus=self.campus).status,
            'Inactive')
        self.assertEqual(HighSchool.objects.get(pk=hs.pk).name, 'Keep renamed')
        self.assertEqual(_status(hs), 'Active')

    def test_individual_update_status_lands_on_link(self):
        hs = _hs('Solo', status='Active')
        _link(hs, self.campus, 'Active')
        HighSchool.import_from_csv(_rows(
            {'name': 'Solo', 'code': hs.code, 'status': 'Inactive'}), use_bulk=False)
        self.assertEqual(
            HighSchoolCampus.objects.get(highschool=hs, campus=self.campus).status,
            'Inactive')
        self.assertEqual(_status(hs), 'Inactive')


@override_settings(MULTI_CAMPUS=True)
class ImportMultiCampusTests(TestCase):
    def setUp(self):
        self.a, self.b = _campus(), _campus()

    def test_bulk_create_links_to_current_campus(self):
        code = _sfx()
        with campus_context(self.b):
            HighSchool.import_from_csv(_rows(
                {'name': 'New', 'code': code, 'status': 'Active'}), use_bulk=True)
        hs = HighSchool.objects.get(code=code)
        self.assertEqual(
            list(hs.campus_links.values_list('campus_id', 'status')),
            [(self.b.pk, 'Active')])

    def test_bulk_update_writes_only_current_campus_link(self):
        hs = _hs('Shared', status='Active')
        _link(hs, self.a, 'Active')
        _link(hs, self.b, 'Active')
        with campus_context(self.a):
            HighSchool.import_from_csv(_rows(
                {'name': 'Shared', 'code': hs.code, 'status': 'Inactive'}),
                use_bulk=True)
        self.assertEqual(
            HighSchoolCampus.objects.get(highschool=hs, campus=self.a).status,
            'Inactive')
        self.assertEqual(
            HighSchoolCampus.objects.get(highschool=hs, campus=self.b).status,
            'Active')
        self.assertEqual(_status(hs), 'Active')

    def test_no_campus_warns_and_leaves_new_school_unlinked(self):
        code = _sfx()
        with self.assertLogs('cis.signals.highschool_campus', 'WARNING'):
            HighSchool.import_from_csv(_rows(
                {'name': 'Orphan', 'code': code, 'status': 'Active'}),
                use_bulk=True)
        self.assertFalse(
            HighSchoolCampus.objects.filter(highschool__code=code).exists())


    def test_staff_import_does_not_link_school_of_another_campus(self):
        hs = _hs('Theirs', status='Active')
        _link(hs, self.a, 'Active')
        with campus_context(self.b):
            for bulk in (True, False):
                result = HighSchool.import_from_csv(_rows(
                    {'name': 'Theirs renamed', 'code': hs.code,
                     'status': 'Inactive'}), use_bulk=bulk)
                self.assertFalse(
                    HighSchoolCampus.objects.filter(
                        highschool=hs, campus=self.b).exists())
                record = result['records'][0]
                self.assertIn('Skipped', record['RESULT'])
                self.assertIn(hs.name, record['RESULT'])
                self.assertIn(hs.code, record['RESULT'])
        hs.refresh_from_db()
        self.assertEqual(hs.name, 'Theirs')
        self.assertEqual(
            HighSchoolCampus.objects.get(highschool=hs, campus=self.a).status,
            'Active')

    def test_staff_import_with_no_status_does_not_touch_unlinked_school(self):
        hs = _hs('Theirs', status='Active')
        _link(hs, self.a, 'Active')
        with campus_context(self.b):
            HighSchool.import_from_csv(_rows(
                {'name': 'Renamed', 'code': hs.code}), use_bulk=True)
        self.assertFalse(HighSchoolCampus.objects.filter(
            highschool=hs, campus=self.b).exists())
        self.assertEqual(HighSchool.objects.get(pk=hs.pk).name, 'Theirs')

    def test_superuser_import_links_school_to_current_campus(self):
        su = User.objects.create_superuser(
            username=f'su-{_sfx()}', email=f'{_sfx()}@x.com', password='x')
        for bulk in (True, False):
            hs = _hs('Theirs', status='Active')
            _link(hs, self.a, 'Active')
            with campus_context(self.b):
                HighSchool.import_from_csv(_rows(
                    {'name': 'Theirs', 'code': hs.code, 'status': 'Inactive'}),
                    use_bulk=bulk, user=su)
            link = HighSchoolCampus.objects.get(highschool=hs, campus=self.b)
            self.assertEqual(link.status, 'Inactive')

    def test_staff_import_updates_already_linked_school(self):
        hs = _hs('Mine', status='Active')
        _link(hs, self.b, 'Active')
        user = User.objects.create_user(
            username=f'st-{_sfx()}', email=f'{_sfx()}@x.com', password='x')
        for bulk, status in ((True, 'Inactive'), (False, 'Active')):
            with campus_context(self.b):
                result = HighSchool.import_from_csv(_rows(
                    {'name': 'Mine', 'code': hs.code, 'status': status}),
                    use_bulk=bulk, user=user)
            self.assertEqual(result['records'][0]['RESULT'], 'Success')
            self.assertEqual(
                HighSchoolCampus.objects.get(highschool=hs, campus=self.b).status,
                status)


# --- C3 + I5b: status form --------------------------------------------------

class _StatusBase(TestCase):
    def _admin_position(self, hs):
        Group.objects.get_or_create(name='highschool_admin')
        user = User.objects.create_user(
            username=f'hsa-{_sfx()}', email=f'{_sfx()}@x.com', password='x')
        admin = HSAdministrator.objects.create(user=user)
        position = HSPosition.objects.create(name=f'P-{_sfx()}')
        return HSAdministratorPosition.objects.create(
            hsadmin=admin, highschool=hs, position=position, status='Active')

    def _post(self, user, hs, status, campus=None, member_status='Inactive'):
        return _call(views.manage_status, user, post={
            'record_id': str(hs.pk), 'action': 'change_status',
            'status': status, 'note': 'why', 'hs_member_status': member_status,
        }, campus=campus)


@override_settings(MULTI_CAMPUS=True)
class StatusMultiCampusTests(_StatusBase):
    def setUp(self):
        self.a, self.b = _campus(), _campus()
        self.hs = _hs('Shared', status='Active')
        _link(self.hs, self.a, 'Active')
        _link(self.hs, self.b, 'Inactive')
        self.pos = self._admin_position(self.hs)
        self.staff = _ce(self.a)

    def test_deactivate_sets_link_derives_status_and_cascades_once(self):
        resp = self._post(self.staff, self.hs, 'Inactive', campus=self.a)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            HighSchoolCampus.objects.get(highschool=self.hs, campus=self.a).status,
            'Inactive')
        self.assertEqual(_status(self.hs), 'Inactive')
        self.assertEqual(
            HSAdministratorPosition.objects.get(pk=self.pos.pk).status, 'Inactive')
        self.assertEqual(HighSchoolNote.objects.filter(highschool=self.hs).count(), 1)

    def test_no_change_adds_no_note_and_no_cascade(self):
        resp = self._post(self.staff, self.hs, 'Active', campus=self.a)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            HSAdministratorPosition.objects.get(pk=self.pos.pk).status, 'Active')
        self.assertFalse(HighSchoolNote.objects.filter(highschool=self.hs).exists())

    def test_other_campus_link_untouched(self):
        self._post(self.staff, self.hs, 'Inactive', campus=self.a)
        self.assertEqual(
            HighSchoolCampus.objects.get(highschool=self.hs, campus=self.b).status,
            'Inactive')

    def test_staff_not_on_campus_forbidden(self):
        other_staff = _ce(_campus())
        c = _campus()
        _link(self.hs, c, 'Active')
        resp = self._post(other_staff, self.hs, 'Inactive', campus=c)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(
            HighSchoolCampus.objects.get(highschool=self.hs, campus=c).status, 'Active')

    def test_superuser_on_host_sets_that_campus(self):
        resp = self._post(_su(), self.hs, 'Active', campus=self.b)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            HighSchoolCampus.objects.get(highschool=self.hs, campus=self.b).status,
            'Active')

    def test_status_of_unscoped_school_is_404(self):
        foreign = _hs('Foreign')
        _link(foreign, self.b)
        with self.assertRaises(Http404):
            self._post(self.staff, foreign, 'Inactive', campus=self.a)
        with self.assertRaises(Http404):
            _call(views.manage_status, self.staff,
                  get={'record_id': str(foreign.pk)}, campus=self.a)


@override_settings(MULTI_CAMPUS=False)
class StatusSingleCampusTests(_StatusBase):
    def setUp(self):
        self.campus = _first_campus()
        self.hs = _hs('Solo', status='Active')
        self.pos = self._admin_position(self.hs)
        # CE staff with no process_campuses rows: single-campus may still manage.
        self.staff = _ce()

    def test_staff_without_process_campuses_sets_link(self):
        _link(self.hs, self.campus, 'Active')
        resp = self._post(self.staff, self.hs, 'Inactive')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(HighSchoolCampus.objects.get(highschool=self.hs).status, 'Inactive')
        self.assertEqual(_status(self.hs), 'Inactive')

    def test_missing_link_created_on_deployment_campus(self):
        # Unlinked schools are hidden from staff; a superuser reaches them.
        resp = self._post(_su(), self.hs, 'Inactive')
        self.assertEqual(resp.status_code, 200, resp.content)
        link = HighSchoolCampus.objects.get(highschool=self.hs)
        self.assertEqual((link.campus_id, link.status), (self.campus.pk, 'Inactive'))
        self.assertEqual(_status(self.hs), 'Inactive')
        self.assertEqual(
            HSAdministratorPosition.objects.get(pk=self.pos.pk).status, 'Inactive')


# --- I5b: can_manage_link ---------------------------------------------------

class CanManageLinkTests(TestCase):
    def setUp(self):
        self.a, self.b = _campus(), _campus()
        self.staff = _ce()           # no process_campuses rows
        self.staff_a = _ce(self.a)
        self.outsider = User.objects.create_user(
            username=f'x-{_sfx()}', email=f'{_sfx()}@x.com', password='x')

    @override_settings(MULTI_CAMPUS=False)
    def test_single_campus_any_ce_staff(self):
        from cis.highschool_scope import can_manage_link
        self.assertTrue(can_manage_link(self.staff, self.a))
        self.assertTrue(can_manage_link(_su(), self.a))
        self.assertFalse(can_manage_link(self.outsider, self.a))

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_process_campuses(self):
        from cis.highschool_scope import can_manage_link
        self.assertTrue(can_manage_link(self.staff_a, self.a))
        self.assertFalse(can_manage_link(self.staff_a, self.b))
        self.assertFalse(can_manage_link(self.staff, self.a))
        self.assertTrue(can_manage_link(_su(), self.b))


@override_settings(MULTI_CAMPUS=False)
class CampusesTabSingleCampusTests(TestCase):
    def setUp(self):
        self.campus = _first_campus()
        self.staff = _ce()           # no process_campuses rows
        self.hs = _hs('Solo')
        self.link = _link(self.hs, self.campus, 'Active', 'S1')

    def test_tab_offers_actions(self):
        body = _call(views.tab, self.staff, record_id=self.hs.id,
                     tab_slug='campuses').content.decode()
        self.assertIn(str(self.link.id), body)

    def test_edit_link(self):
        resp = _call(views.highschool_campus_edit, self.staff, post={
            'apply': '1', 'building_code': 'S2', 'status': 'Inactive'},
            link_id=self.link.id)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.link.refresh_from_db()
        self.assertEqual((self.link.building_code, self.link.status), ('S2', 'Inactive'))

    def test_add_link_to_other_campus(self):
        other = _campus('zz-other')
        resp = _call(views.highschool_campus_add, self.staff, post={
            'apply': '1', 'campus': str(other.id), 'status': 'Active'},
            record_id=self.hs.id)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(
            HighSchoolCampus.objects.filter(highschool=self.hs, campus=other).exists())


# --- I1: scoped CE endpoints -----------------------------------------------

@override_settings(MULTI_CAMPUS=True)
class ScopedEndpointTests(TestCase):
    def setUp(self):
        self.a, self.b = _campus(), _campus()
        self.staff = _ce(self.a)
        self.mine = _hs('Mine Alpha')
        _link(self.mine, self.a)
        self.foreign = _hs('Foreign Alpha')
        _link(self.foreign, self.b)
        self.shared = _hs('Shared Alpha')
        _link(self.shared, self.a)
        _link(self.shared, self.b)

    def test_delete_foreign_school_is_404(self):
        with self.assertRaises(Http404):
            _call(views.delete, self.staff, post={}, campus=self.a,
                  record_id=self.foreign.pk)
        self.assertTrue(HighSchool.objects.filter(pk=self.foreign.pk).exists())

    def test_delete_school_also_on_other_campus_is_403(self):
        resp = _call(views.delete, self.staff, post={}, campus=self.a,
                     record_id=self.shared.pk)
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(HighSchool.objects.filter(pk=self.shared.pk).exists())

    def test_delete_own_school(self):
        resp = _call(views.delete, self.staff, post={}, campus=self.a,
                     record_id=self.mine.pk)
        self.assertEqual(json.loads(resp.content)['status'], 'success')
        self.assertFalse(HighSchool.objects.filter(pk=self.mine.pk).exists())

    def test_superuser_may_delete_shared(self):
        resp = _call(views.delete, _su(), post={}, campus=self.a,
                     record_id=self.shared.pk)
        self.assertEqual(json.loads(resp.content)['status'], 'success')

    def _bulk(self, view, extra):
        post = {'ids[]': [str(self.mine.pk), str(self.foreign.pk)], 'apply': '1'}
        post.update(extra)
        return _call(view, self.staff, post=post, campus=self.a)

    def test_set_is_cte_skips_foreign(self):
        resp = self._bulk(views.set_is_cte, {'is_cte': '1'})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(HighSchool.objects.get(pk=self.mine.pk).is_cte)
        self.assertFalse(HighSchool.objects.get(pk=self.foreign.pk).is_cte)

    def test_set_hs_type_skips_foreign(self):
        from cis.services.tenant_services import get_tenant_service
        codes = list(get_tenant_service('highschool_types').codes())
        if not codes:
            self.skipTest('tenant has no high school types')
        before = HighSchool.objects.get(pk=self.foreign.pk).hs_type
        resp = self._bulk(views.set_hs_type, {'hs_type': [codes[0]]})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(list(HighSchool.objects.get(pk=self.mine.pk).hs_type), [codes[0]])
        self.assertEqual(HighSchool.objects.get(pk=self.foreign.pk).hs_type, before)

    def test_ajax_search_scoped(self):
        resp = _call(views.ajax_search, self.staff, get={'q': 'Alpha'}, campus=self.a)
        names = {i['name'] for i in json.loads(resp.content)['items']}
        self.assertEqual(names, {'Mine Alpha', 'Shared Alpha'})

    def test_event_ajax_search_scoped(self):
        from cis.views import event
        resp = _call(event.ajax_search, self.staff, get={'q': 'Alpha'}, campus=self.a)
        names = {i['name'] for i in json.loads(resp.content)['items']}
        self.assertEqual(names, {'Mine Alpha', 'Shared Alpha'})


# --- I2: report and settings pickers ---------------------------------------

@override_settings(MULTI_CAMPUS=True)
class ReportPickerTests(TestCase):
    def setUp(self):
        self.a, self.b = _campus(), _campus()
        self.staff = _ce(self.a)
        self.mine = _hs('Mine', status='Active')
        _link(self.mine, self.a)
        self.dormant = _hs('Dormant')
        _link(self.dormant, self.a, 'Inactive')
        self.foreign = _hs('Foreign', status='Active')
        _link(self.foreign, self.b)

    def _req(self):
        req = RequestFactory().get('/x', {'report_id': str(uuid.uuid4())})
        req.user = self.staff
        return req

    def test_picker_reports(self):
        from cis.reports.class_export import class_export
        from cis.reports.teacher_export import teacher_export
        with campus_context(self.a):
            for form, field in ((teacher_export(self._req()), 'highschools'),
                                (class_export(self._req()), 'highschool')):
                self.assertEqual(
                    list(form.fields[field].queryset), [self.mine], type(form).__name__)

    def test_class_roster_ce_lists_campus_schools_any_status(self):
        from cis.reports.class_roster import class_roster
        with campus_context(self.a):
            form = class_roster(self._req())
            self.assertEqual(
                {h.pk for h in form.fields['highschool'].queryset},
                {self.mine.pk, self.dormant.pk})

    def test_registration_settings_homeschool_keeps_current(self):
        from cis.models.settings import Setting
        from cis.settings.registrations import registrations
        req = self._req()
        with campus_context(self.a):
            Setting.objects.update_or_create(
                key=registrations.key,
                defaults={'value': {'homeschool': str(self.foreign.pk)}})
            form = registrations(req, initial=registrations.from_db())
            ids = [c for c, _l in form.fields['homeschool'].choices if c]
        self.assertEqual(set(ids), {str(self.mine.pk), str(self.foreign.pk)})


# --- I6: merge ---------------------------------------------------------------

@override_settings(MULTI_CAMPUS=True)
class MergeTests(TestCase):
    def setUp(self):
        self.a, self.b, self.c = _campus(), _campus(), _campus()
        self.x = _hs('Duplicate')
        self.s = _hs('Survivor')
        _link(self.x, self.a, 'Active', 'XA')
        _link(self.x, self.b, 'Inactive', 'XB')
        _link(self.s, self.b, 'Active', 'SB')
        _link(self.s, self.c, 'Inactive', 'SC')
        # A stale school status: the merge must re-derive it.
        HighSchool.objects.filter(pk=self.s.pk).update(status='Inactive')

    def test_references_exclude_campus_links(self):
        from cis.utils import get_foreign_key_references
        names = {name for name, _o in get_foreign_key_references(self.x)}
        self.assertFalse(
            names & {'Campus', 'HighSchoolCampus', 'HistoricalHighSchoolCampus'}, names)

    def test_merge_moves_links_and_rederives_status(self):
        from cis.forms.highschool import MigrateForm
        # Both schools are linked to campus b, where the merge is done.
        with campus_context(self.b):
            form = MigrateForm(record=self.x, data={
                'action': 'migrate_highschool',
                'destination_record': str(self.s.pk),
                'move_items': [],
                'confirm': 'on',
            })
            form.fields['move_items'].required = False
            self.assertTrue(form.is_valid(), form.errors)
            form.save(None, self.x)
        links = dict(HighSchoolCampus.objects.filter(highschool=self.s)
                     .values_list('campus_id', 'building_code'))
        self.assertEqual(links, {self.a.pk: 'XA', self.b.pk: 'SB', self.c.pk: 'SC'})
        self.assertEqual(
            HighSchoolCampus.objects.get(highschool=self.s, campus=self.b).status, 'Active')
        self.assertFalse(HighSchoolCampus.objects.filter(highschool=self.x).exists())
        self.assertEqual(_status(self.s), 'Active')


# --- minors ------------------------------------------------------------------

@override_settings(MULTI_CAMPUS=True)
class MinorTests(TestCase):
    def test_picker_keep_blank_is_none(self):
        from cis.highschool_scope import picker_queryset
        a = _campus()
        hs = _hs('Mine')
        _link(hs, a)
        self.assertEqual(list(picker_queryset(a, keep='')), [hs])
        self.assertEqual(list(picker_queryset(a, keep=None)), [hs])

    def test_verbose_name_plural(self):
        self.assertEqual(
            str(HighSchoolCampus._meta.verbose_name_plural), 'high school campuses')
        self.assertEqual(
            str(HighSchoolCampus.history.model._meta.verbose_name_plural),
            'historical high school campuses')
