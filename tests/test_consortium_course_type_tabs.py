"""Consortiums and Course Types tabs on the high school detail page, their
membership / approval actions, the two CE master pages and the
course_type_gate setting (phase 2 of ewu
docs/plans/highschool-consortium-and-course-types.md)."""
import json
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings

from cis.campus_context import campus_context
from cis.models import (
    Consortium, ConsortiumMembership, CourseType, HighSchoolCourseType)
from cis.models.course import Campus
from cis.models.highschool import HighSchool, HighSchoolCampus
from cis.models.settings import Setting
from cis.settings.course_type_gate import course_type_gate
from cis.signals.staff_campus import set_process_campuses
from cis.views import consortium as consortium_views
from cis.views import course_type as course_type_views
from cis.views import highschool as hs_views

User = get_user_model()
PREFIX = settings.CAMPUS_CODE_PREFIX


def _sfx():
    return uuid.uuid4().hex[:8]


def _campus():
    return Campus.objects.create(name=f'C-{_sfx()}', code=f'{PREFIX}_{_sfx()}')


def _hs(name=None, campus=None):
    hs = HighSchool.objects.create(name=name or f'HS-{_sfx()}', code=_sfx())
    HighSchoolCampus.objects.filter(highschool=hs).delete()
    if campus is not None:
        HighSchoolCampus.objects.create(highschool=hs, campus=campus)
    return hs


def _course_type(**kw):
    kw.setdefault('code', f'ct_{_sfx()}')
    kw.setdefault('name', f'Type {kw["code"]}')
    return CourseType.objects.create(**kw)


def _set_gate(**values):
    Setting.objects.update_or_create(
        key=course_type_gate.key, defaults={'value': values})


class _Base(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='ce')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@x.com'})
        self.staff = self._user('ce')
        self.su = User.objects.create_superuser(
            username=f'su-{_sfx()}', email=f'{_sfx()}@x.com', password='x')
        self.su.groups.add(Group.objects.get(name='ce'))
        self.nobody = User.objects.create_user(
            username=f'n-{_sfx()}', email=f'{_sfx()}@x.com', password='x')

    def _user(self, group):
        user = User.objects.create_user(
            username=f'{group}-{_sfx()}', email=f'{_sfx()}@x.com', password='x')
        user.groups.add(Group.objects.get(name=group))
        return user

    def _call(self, view, user, post=None, campus=None, **kwargs):
        rf = RequestFactory()
        req = rf.post('/x', post) if post is not None else rf.get('/x')
        req.user = user
        if campus is not None:
            with campus_context(campus):
                return view(req, **kwargs)
        return view(req, **kwargs)

    def _json(self, resp):
        return json.loads(resp.content)


class TabRegistrationTests(TestCase):
    def test_tabs_sit_between_campuses_and_instructors(self):
        from myce.component_registry.highschool import highschool_tabs
        slugs = [slug for slug, _t in sorted(
            highschool_tabs._tabs.items(), key=lambda kv: kv[1]['order'])]
        at = slugs.index('campuses')
        self.assertEqual(
            slugs[at:at + 4], ['campuses', 'consortiums', 'course_types', 'instructors'])


class ConsortiumsTabTests(_Base):
    def setUp(self):
        super().setUp()
        self.hs, self.sibling = _hs('Alpha'), _hs('Bravo')
        self.consortium = Consortium.objects.create(name=f'North-{_sfx()}')
        self.member = ConsortiumMembership.objects.create(
            consortium=self.consortium, highschool=self.hs,
            billing_basis=ConsortiumMembership.BILLING_HOME_SCHOOL)
        ConsortiumMembership.objects.create(
            consortium=self.consortium, highschool=self.sibling)

    def test_tab_lists_memberships_and_other_members(self):
        body = self._call(hs_views.tab, self.staff, record_id=self.hs.id,
                          tab_slug='consortiums').content.decode()
        self.assertIn(self.consortium.name, body)
        self.assertIn("Student&#x27;s home school&#x27;s pay type", body)
        self.assertIn('Bravo', body)
        self.assertIn(str(self.member.id), body)

    def test_tab_empty_state(self):
        body = self._call(hs_views.tab, self.staff, record_id=_hs().id,
                          tab_slug='consortiums').content.decode()
        self.assertIn('Not a member of any consortium', body)


class MembershipAddTests(_Base):
    def setUp(self):
        super().setUp()
        self.hs = _hs()
        self.consortium = Consortium.objects.create(name=f'North-{_sfx()}')

    def _add(self, user, post):
        return self._call(consortium_views.membership_add, user, post=post,
                          record_id=self.hs.id)

    def test_first_post_returns_modal(self):
        resp = self._add(self.staff, {})
        self.assertEqual(self._json(resp)['outcome'], 'modal')
        self.assertIn('billing_basis', self._json(resp)['html'])

    def test_join_existing_consortium(self):
        resp = self._add(self.staff, {
            'apply': '1', 'consortium': str(self.consortium.id),
            'billing_basis': 'student_pay', 'status': 'Active',
            'joined_on': '2026-08-01'})
        self.assertEqual(resp.status_code, 200, resp.content)
        member = ConsortiumMembership.objects.get(highschool=self.hs)
        self.assertEqual(member.consortium, self.consortium)
        self.assertEqual(member.billing_basis, 'student_pay')
        self.assertEqual(str(member.joined_on), '2026-08-01')

    def test_create_consortium_inline(self):
        resp = self._add(self.staff, {
            'apply': '1', 'new_consortium_name': 'South Valley',
            'new_consortium_description': 'Three schools',
            'billing_basis': 'host_school', 'status': 'Active'})
        self.assertEqual(resp.status_code, 200, resp.content)
        created = Consortium.objects.get(name='South Valley')
        self.assertEqual(created.description, 'Three schools')
        self.assertTrue(created.memberships.filter(highschool=self.hs).exists())

    def test_pick_and_create_together_is_error(self):
        resp = self._add(self.staff, {
            'apply': '1', 'consortium': str(self.consortium.id),
            'new_consortium_name': 'Other', 'billing_basis': 'host_school',
            'status': 'Active'})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(ConsortiumMembership.objects.exists())

    def test_neither_pick_nor_create_is_error(self):
        resp = self._add(self.staff, {
            'apply': '1', 'billing_basis': 'host_school', 'status': 'Active'})
        self.assertEqual(resp.status_code, 400)

    def test_inline_name_clash_is_error(self):
        resp = self._add(self.staff, {
            'apply': '1', 'new_consortium_name': self.consortium.name.upper(),
            'billing_basis': 'host_school', 'status': 'Active'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Consortium.objects.count(), 1)

    def test_joining_twice_is_form_error(self):
        ConsortiumMembership.objects.create(consortium=self.consortium, highschool=self.hs)
        resp = self._add(self.staff, {
            'apply': '1', 'consortium': str(self.consortium.id),
            'billing_basis': 'host_school', 'status': 'Active'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ConsortiumMembership.objects.count(), 1)

    def test_inactive_consortium_not_offered(self):
        Consortium.objects.create(name='Retired Group', status='Inactive')
        html = self._json(self._add(self.staff, {}))['html']
        self.assertIn(self.consortium.name, html)
        self.assertNotIn('Retired Group', html)

    def test_non_ce_forbidden(self):
        resp = self._add(self.nobody, {
            'apply': '1', 'consortium': str(self.consortium.id),
            'billing_basis': 'host_school', 'status': 'Active'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(ConsortiumMembership.objects.exists())


class MembershipEditDeleteTests(_Base):
    def setUp(self):
        super().setUp()
        self.hs = _hs()
        self.member = ConsortiumMembership.objects.create(
            consortium=Consortium.objects.create(name=f'North-{_sfx()}'),
            highschool=self.hs)

    def test_edit_changes_billing_basis_and_status(self):
        resp = self._call(consortium_views.membership_edit, self.staff, post={
            'apply': '1', 'billing_basis': 'home_school', 'status': 'Inactive'},
            membership_id=self.member.id)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.member.refresh_from_db()
        self.assertEqual((self.member.billing_basis, self.member.status),
                         ('home_school', 'Inactive'))

    def test_edit_cannot_move_to_another_consortium(self):
        other = Consortium.objects.create(name=f'Other-{_sfx()}')
        self._call(consortium_views.membership_edit, self.staff, post={
            'apply': '1', 'consortium': str(other.id),
            'billing_basis': 'host_school', 'status': 'Active'},
            membership_id=self.member.id)
        self.member.refresh_from_db()
        self.assertNotEqual(self.member.consortium, other)

    def test_delete_confirms_then_removes(self):
        first = self._call(consortium_views.membership_delete, self.staff, post={},
                           membership_id=self.member.id)
        self.assertEqual(self._json(first)['outcome'], 'modal')
        resp = self._call(consortium_views.membership_delete, self.staff,
                          post={'apply': '1'}, membership_id=self.member.id)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ConsortiumMembership.objects.filter(pk=self.member.pk).exists())

    def test_non_ce_cannot_delete(self):
        resp = self._call(consortium_views.membership_delete, self.nobody,
                          post={'apply': '1'}, membership_id=self.member.id)
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(ConsortiumMembership.objects.filter(pk=self.member.pk).exists())


@override_settings(MULTI_CAMPUS=True)
class MultiCampusScopeTests(_Base):
    def setUp(self):
        super().setUp()
        self.a, self.b = _campus(), _campus()
        set_process_campuses(self.staff, [self.a])
        self.hs_b = _hs(campus=self.b)

    def test_membership_add_out_of_scope_school_404s(self):
        from django.http import Http404
        consortium = Consortium.objects.create(name=f'North-{_sfx()}')
        with self.assertRaises(Http404):
            self._call(consortium_views.membership_add, self.staff, post={
                'apply': '1', 'consortium': str(consortium.id),
                'billing_basis': 'host_school', 'status': 'Active'},
                campus=self.a, record_id=self.hs_b.id)
        self.assertFalse(ConsortiumMembership.objects.exists())


class CourseTypesTabTests(_Base):
    def setUp(self):
        super().setUp()
        self.hs = _hs()
        self.online = _course_type(code='online', name='Online')
        self.link = HighSchoolCourseType.objects.create(
            highschool=self.hs, course_type=self.online)

    def test_tab_lists_approvals(self):
        body = self._call(hs_views.tab, self.staff, record_id=self.hs.id,
                          tab_slug='course_types').content.decode()
        self.assertIn('Online', body)
        self.assertIn(str(self.link.id), body)
        self.assertNotIn('Campus</th>', body)  # single-campus: no column

    def test_warning_only_when_gate_on_and_nothing_approved(self):
        bare = _hs()
        off = self._call(hs_views.tab, self.staff, record_id=bare.id,
                         tab_slug='course_types').content.decode()
        self.assertNotIn('see no on-campus or online sections', off)
        _set_gate(enabled=True)
        on = self._call(hs_views.tab, self.staff, record_id=bare.id,
                        tab_slug='course_types').content.decode()
        self.assertIn('see no on-campus or online sections', on)


class CourseTypeApproveTests(_Base):
    def setUp(self):
        super().setUp()
        self.hs = _hs()
        self.f2f = _course_type(code='face_to_face', name='Face-to-Face')
        self.online = _course_type(code='online', name='Online')
        self.dev = _course_type(code='developmental', name='Developmental',
                                approvable=False)
        self.retired = _course_type(code='retired', name='Retired', status='Inactive')

    def _add(self, user, post, **kw):
        return self._call(course_type_views.highschool_course_type_add, user,
                          post=post, record_id=self.hs.id, **kw)

    def test_modal_offers_only_active_approvable_types(self):
        html = self._json(self._add(self.staff, {}))['html']
        self.assertIn('Face-to-Face', html)
        self.assertIn('Online', html)
        self.assertNotIn('Developmental', html)
        self.assertNotIn('Retired', html)

    def test_approve_several_in_one_save(self):
        resp = self._add(self.staff, {
            'apply': '1', 'course_types': [str(self.f2f.id), str(self.online.id)]})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(set(self.hs.approved_course_types.all()), {self.f2f, self.online})
        self.assertTrue(all(link.campus_id is None
                            for link in self.hs.course_type_links.all()))

    def test_non_approvable_type_rejected_even_if_posted(self):
        resp = self._add(self.staff, {'apply': '1', 'course_types': [str(self.dev.id)]})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(self.hs.course_type_links.exists())

    def test_already_approved_type_not_offered(self):
        HighSchoolCourseType.objects.create(highschool=self.hs, course_type=self.online)
        html = self._json(self._add(self.staff, {}))['html']
        self.assertNotIn('Online', html)

    def test_nothing_selected_is_error(self):
        resp = self._add(self.staff, {'apply': '1'})
        self.assertEqual(resp.status_code, 400)

    def test_create_from_tab_off_by_default(self):
        html = self._json(self._add(self.staff, {}))['html']
        self.assertNotIn('new_code', html)
        resp = self._add(self.staff, {
            'apply': '1', 'new_code': 'hyflex', 'new_name': 'HyFlex'})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(CourseType.objects.filter(code='hyflex').exists())

    def test_create_from_tab_when_setting_on(self):
        _set_gate(allow_create_from_tab=True)
        self.assertIn('new_code', self._json(self._add(self.staff, {}))['html'])
        resp = self._add(self.staff, {
            'apply': '1', 'new_code': 'hyflex', 'new_name': 'HyFlex'})
        self.assertEqual(resp.status_code, 200, resp.content)
        hyflex = CourseType.objects.get(code='hyflex')
        self.assertTrue(self.hs.approved_course_types.filter(pk=hyflex.pk).exists())

    def test_create_from_tab_rejects_existing_code(self):
        _set_gate(allow_create_from_tab=True)
        resp = self._add(self.staff, {
            'apply': '1', 'new_code': 'online', 'new_name': 'Online again'})
        self.assertEqual(resp.status_code, 400)

    def test_non_ce_forbidden(self):
        resp = self._add(self.nobody, {'apply': '1', 'course_types': [str(self.f2f.id)]})
        self.assertEqual(resp.status_code, 403)


@override_settings(MULTI_CAMPUS=True)
class CourseTypeCampusTests(_Base):
    def setUp(self):
        super().setUp()
        self.a, self.b, self.c = _campus(), _campus(), _campus()
        set_process_campuses(self.staff, [self.a, self.c])
        self.hs = _hs(campus=self.a)
        HighSchoolCampus.objects.create(highschool=self.hs, campus=self.b)
        self.online = _course_type(code=f'on_{_sfx()}', name='Online')

    def _add(self, user, post):
        return self._call(course_type_views.highschool_course_type_add, user,
                          post=post, campus=self.a, record_id=self.hs.id)

    def test_staff_approves_for_a_campus_they_manage(self):
        resp = self._add(self.staff, {
            'apply': '1', 'course_types': [str(self.online.id)], 'campus': str(self.a.id)})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self.hs.course_type_links.get().campus, self.a)

    def test_staff_cannot_approve_for_unmanaged_campus(self):
        resp = self._add(self.staff, {
            'apply': '1', 'course_types': [str(self.online.id)], 'campus': str(self.b.id)})
        self.assertIn(resp.status_code, (400, 403))
        self.assertFalse(self.hs.course_type_links.exists())

    def test_staff_cannot_approve_all_campuses(self):
        resp = self._add(self.staff, {
            'apply': '1', 'course_types': [str(self.online.id)], 'campus': ''})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(self.hs.course_type_links.exists())

    def test_superuser_approves_all_campuses(self):
        resp = self._add(self.su, {
            'apply': '1', 'course_types': [str(self.online.id)], 'campus': ''})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNone(self.hs.course_type_links.get().campus)

    def test_overlap_with_all_campus_approval_is_error(self):
        HighSchoolCourseType.objects.create(highschool=self.hs, course_type=self.online)
        resp = self._add(self.su, {
            'apply': '1', 'course_types': [str(self.online.id)], 'campus': str(self.a.id)})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.hs.course_type_links.count(), 1)

    def test_same_campus_twice_is_error(self):
        HighSchoolCourseType.objects.create(
            highschool=self.hs, course_type=self.online, campus=self.a)
        resp = self._add(self.staff, {
            'apply': '1', 'course_types': [str(self.online.id)], 'campus': str(self.a.id)})
        self.assertEqual(resp.status_code, 400)

    def test_tab_shows_campus_column_and_actions_only_where_manageable(self):
        mine = HighSchoolCourseType.objects.create(
            highschool=self.hs, course_type=self.online, campus=self.a)
        other_type = _course_type(code=f'f2f_{_sfx()}', name='F2F')
        theirs = HighSchoolCourseType.objects.create(
            highschool=self.hs, course_type=other_type, campus=self.b)
        body = self._call(hs_views.tab, self.staff, campus=self.a,
                          record_id=self.hs.id, tab_slug='course_types').content.decode()
        self.assertIn('Campus</th>', body)
        self.assertIn(str(mine.id), body)
        self.assertNotIn(str(theirs.id), body)

    def test_staff_cannot_edit_link_on_unmanaged_campus(self):
        theirs = HighSchoolCourseType.objects.create(
            highschool=self.hs, course_type=self.online, campus=self.b)
        resp = self._call(course_type_views.highschool_course_type_delete, self.staff,
                          post={'apply': '1'}, campus=self.a, link_id=theirs.id)
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(HighSchoolCourseType.objects.filter(pk=theirs.pk).exists())


class CourseTypeLinkEditDeleteTests(_Base):
    def setUp(self):
        super().setUp()
        self.hs = _hs()
        self.link = HighSchoolCourseType.objects.create(
            highschool=self.hs, course_type=_course_type())

    def test_edit_status(self):
        resp = self._call(course_type_views.highschool_course_type_edit, self.staff,
                          post={'apply': '1', 'status': 'Inactive'}, link_id=self.link.id)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, 'Inactive')

    def test_delete(self):
        resp = self._call(course_type_views.highschool_course_type_delete, self.staff,
                          post={'apply': '1'}, link_id=self.link.id)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(HighSchoolCourseType.objects.filter(pk=self.link.pk).exists())


class ConsortiumMasterPageTests(_Base):
    def test_index_lists_consortiums_with_member_counts(self):
        consortium = Consortium.objects.create(name='East Valley')
        for hs in (_hs(), _hs()):
            ConsortiumMembership.objects.create(consortium=consortium, highschool=hs)
        resp = self._call(consortium_views.index, self.staff)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('East Valley', body)
        self.assertIn('>2<', body)

    def test_add_and_edit(self):
        resp = self._call(consortium_views.consortium_add, self.staff, post={
            'apply': '1', 'name': 'West', 'description': '', 'status': 'Active'})
        self.assertEqual(resp.status_code, 200, resp.content)
        west = Consortium.objects.get(name='West')
        resp = self._call(consortium_views.consortium_edit, self.staff, post={
            'apply': '1', 'name': 'West Valley', 'description': 'x', 'status': 'Inactive'},
            record_id=west.id)
        self.assertEqual(resp.status_code, 200, resp.content)
        west.refresh_from_db()
        self.assertEqual((west.name, west.status), ('West Valley', 'Inactive'))

    def test_detail_lists_members(self):
        consortium = Consortium.objects.create(name='East Valley')
        ConsortiumMembership.objects.create(consortium=consortium, highschool=_hs('Charlie'))
        body = self._call(consortium_views.detail, self.staff,
                          record_id=consortium.id).content.decode()
        self.assertIn('Charlie', body)

    def test_non_ce_forbidden(self):
        resp = self._call(consortium_views.consortium_add, self.nobody, post={
            'apply': '1', 'name': 'Nope', 'status': 'Active'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Consortium.objects.exists())


class CourseTypeMasterPageTests(_Base):
    def test_index_lists_types(self):
        _course_type(code='online', name='Online')
        resp = self._call(course_type_views.index, self.staff)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Online', resp.content.decode())

    def test_add_validates_code_shape(self):
        resp = self._call(course_type_views.course_type_add, self.staff, post={
            'apply': '1', 'code': 'Face To Face', 'name': 'F2F', 'sort_order': '0',
            'status': 'Active', 'approvable': 'on'})
        self.assertEqual(resp.status_code, 400)
        resp = self._call(course_type_views.course_type_add, self.staff, post={
            'apply': '1', 'code': 'face_to_face', 'name': 'F2F', 'sort_order': '1',
            'status': 'Active', 'approvable': 'on'})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(CourseType.objects.filter(code='face_to_face').exists())

    def test_edit_keeps_code(self):
        course_type = _course_type(code='online', name='Online')
        resp = self._call(course_type_views.course_type_edit, self.staff, post={
            'apply': '1', 'code': 'web', 'name': 'Online (web)', 'sort_order': '2',
            'status': 'Active'}, record_id=course_type.id)
        self.assertEqual(resp.status_code, 200, resp.content)
        course_type.refresh_from_db()
        self.assertEqual((course_type.code, course_type.name, course_type.approvable),
                         ('online', 'Online (web)', False))

    def test_non_ce_forbidden(self):
        resp = self._call(course_type_views.course_type_add, self.nobody, post={
            'apply': '1', 'code': 'x', 'name': 'X', 'sort_order': '0', 'status': 'Active'})
        self.assertEqual(resp.status_code, 403)


class CourseTypeGateSettingTests(TestCase):
    def test_defaults_are_off(self):
        config = course_type_gate.get_config()
        self.assertFalse(config['enabled'])
        self.assertFalse(config['allow_create_from_tab'])
        self.assertEqual(config['applies_to'], 'college_sections')
        self.assertEqual(config['empty_means'], 'nothing')
        self.assertEqual(config['no_highschool_means'], 'everything')

    def test_stored_values_override_defaults(self):
        _set_gate(enabled=True)
        self.assertTrue(course_type_gate.is_enabled())
        self.assertFalse(course_type_gate.allow_create_from_tab())

    def test_registered_as_configurator(self):
        from cis.apps import CisConfig
        names = [c['name'] for c in CisConfig.CONFIGURATORS]
        self.assertIn('course_type_gate', names)


class MenuMigrationTests(TestCase):
    def setUp(self):
        import importlib
        self.mod = importlib.import_module(
            'cis.migrations.0111_add_consortiums_course_types_nav')

    def _value(self):
        return {'ce_menu': json.dumps([{
            'name': 'highschools', 'sub_menu': [
                {'name': 'all_highschools'}, {'name': 'school_roles'},
                {'name': 'all_districts'},
            ]}])}

    def _names(self, value):
        return [s.get('name') for s in json.loads(value['ce_menu'])[0]['sub_menu']]

    def test_adds_after_admin_roles_once(self):
        value = self.mod._patch_menu(self._value())
        value = self.mod._patch_menu(value)
        self.assertEqual(self._names(value), [
            'all_highschools', 'school_roles', 'consortiums', 'course_types',
            'all_districts'])

    def test_reverse_removes_them(self):
        value = self.mod._patch_menu(self._value())
        value = self.mod._patch_menu(value, remove=True)
        self.assertEqual(self._names(value),
                         ['all_highschools', 'school_roles', 'all_districts'])

    def test_missing_parent_left_untouched(self):
        value = {'ce_menu': json.dumps([{'name': 'users', 'sub_menu': []}])}
        self.assertEqual(self.mod._patch_menu(dict(value)), value)
