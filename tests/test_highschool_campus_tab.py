"""Campuses tab on the high school detail page and its link actions."""
import json
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from cis.campus_context import campus_context
from cis.campus_gate import get_accessible_campuses
from cis.forms.highschool_campus import HighSchoolCampusForm
from cis.models.course import Campus
from cis.models.highschool import HighSchool, HighSchoolCampus
from cis.signals.staff_campus import set_process_campuses
from cis.views import highschool as views

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


def _campus():
    return Campus.objects.create(
        name=f'C-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}_{_sfx()}')


def _hs(name):
    hs = HighSchool.objects.create(name=name, code=_sfx())
    HighSchoolCampus.objects.filter(highschool=hs).delete()
    return hs


def _link(hs, campus, code='', status='Active'):
    return HighSchoolCampus.objects.create(
        highschool=hs, campus=campus, building_code=code, status=status)


@override_settings(MULTI_CAMPUS=True)
class _Base(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='ce')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@x.com'})
        self.a, self.b, self.c = _campus(), _campus(), _campus()
        self.staff = User.objects.create_user(
            username=f'ce-{_sfx()}', email=f'{_sfx()}@x.com', password='x')
        self.staff.groups.add(Group.objects.get(name='ce'))
        set_process_campuses(self.staff, [self.a, self.c])
        self.su = User.objects.create_superuser(
            username=f'su-{_sfx()}', email=f'{_sfx()}@x.com', password='x')
        self.su.groups.add(Group.objects.get(name='ce'))
        self.hs = _hs('Alpha')
        self.link_a = _link(self.hs, self.a, 'AA')
        self.link_b = _link(self.hs, self.b, 'BB')

    def _call(self, view, user, post=None, campus=None, **kwargs):
        rf = RequestFactory()
        req = rf.post('/x', post) if post is not None else rf.get('/x')
        req.user = user
        with campus_context(campus or self.a):
            return view(req, **kwargs)

    def _json(self, resp):
        return json.loads(resp.content)


class TabTests(_Base):
    def test_tab_registered_after_first_tab(self):
        from myce.component_registry.highschool import highschool_tabs
        slugs = [slug for slug, _t in sorted(
            highschool_tabs._tabs.items(), key=lambda kv: kv[1]['order'])]
        self.assertEqual(slugs[slugs.index('campuses') - 1], 'details')
        self.assertEqual(slugs[slugs.index('campuses') + 1], 'instructors')

    def test_tab_renders_links(self):
        resp = self._call(views.tab, self.staff, record_id=self.hs.id,
                          tab_slug='campuses')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(self.a.name, body)
        self.assertIn(self.b.name, body)
        self.assertIn('AA', body)
        self.assertIn('BB', body)

    def test_actions_only_for_processable_links(self):
        body = self._call(views.tab, self.staff, record_id=self.hs.id,
                          tab_slug='campuses').content.decode()
        self.assertIn(str(self.link_a.id), body)
        self.assertNotIn(str(self.link_b.id), body)


class AddTests(_Base):
    def _add(self, user, post=None):
        return self._call(views.highschool_campus_add, user, post=post,
                          record_id=self.hs.id)

    def test_first_post_returns_modal(self):
        resp = self._add(self.staff, {})
        self.assertEqual(self._json(resp)['outcome'], 'modal')

    def test_add_creates_link(self):
        resp = self._add(self.staff, {
            'apply': '1', 'campus': str(self.c.id),
            'building_code': 'CC', 'status': 'Inactive'})
        self.assertEqual(resp.status_code, 200, resp.content)
        link = HighSchoolCampus.objects.get(highschool=self.hs, campus=self.c)
        self.assertEqual((link.building_code, link.status), ('CC', 'Inactive'))

    def test_add_existing_link_is_form_error_not_duplicate(self):
        resp = self._add(self.staff, {
            'apply': '1', 'campus': str(self.a.id), 'status': 'Active'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            HighSchoolCampus.objects.filter(highschool=self.hs, campus=self.a).count(), 1)

    def test_add_other_campus_forbidden(self):
        resp = self._add(self.staff, {
            'apply': '1', 'campus': str(self.b.id), 'status': 'Active'})
        self.assertEqual(resp.status_code, 403)

    def test_duplicate_code_names_other_school(self):
        other = _hs('Zulu Academy')
        _link(other, self.c, 'ZZ')
        resp = self._add(self.staff, {
            'apply': '1', 'campus': str(self.c.id),
            'building_code': 'ZZ', 'status': 'Active'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Zulu Academy', resp.content.decode())
        self.assertFalse(
            HighSchoolCampus.objects.filter(highschool=self.hs, campus=self.c).exists())

    def test_non_ce_forbidden(self):
        nobody = User.objects.create_user(
            username=f'n-{_sfx()}', email=f'{_sfx()}@x.com', password='x')
        resp = self._add(nobody, {'apply': '1', 'campus': str(self.c.id)})
        self.assertEqual(resp.status_code, 403)

    def test_superuser_may_add_any_campus(self):
        resp = self._add(self.su, {
            'apply': '1', 'campus': str(self.c.id), 'status': 'Active'})
        self.assertEqual(resp.status_code, 200, resp.content)


class RaceAndInputTests(_Base):
    def test_non_uuid_campus_is_form_error_not_500(self):
        resp = self._call(views.highschool_campus_add, self.staff, post={
            'apply': '1', 'campus': 'not-a-uuid', 'status': 'Active'},
            record_id=self.hs.id)
        self.assertEqual(resp.status_code, 400)

    def test_add_duplicate_link_race_is_form_error(self):
        from unittest import mock
        real_clean = HighSchoolCampusForm._post_clean

        def clean_then_race(form):
            out = real_clean(form)
            _link(self.hs, self.c, 'RC')  # concurrent submit wins
            return out
        with mock.patch.object(HighSchoolCampusForm, "_post_clean", clean_then_race):
            resp = self._call(views.highschool_campus_add, self.staff, post={
                'apply': '1', 'campus': str(self.c.id),
                'building_code': 'RC2', 'status': 'Active'},
                record_id=self.hs.id)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('already linked', resp.content.decode())
        self.assertEqual(
            HighSchoolCampus.objects.filter(highschool=self.hs, campus=self.c).count(), 1)

    def test_code_race_names_school(self):
        from unittest import mock
        other = _hs('Xray Prep')
        real_clean = HighSchoolCampusForm._post_clean

        def clean_then_race(form):
            out = real_clean(form)
            _link(other, self.c, 'RACE')
            return out
        with mock.patch.object(HighSchoolCampusForm, "_post_clean", clean_then_race):
            resp = self._call(views.highschool_campus_add, self.staff, post={
                'apply': '1', 'campus': str(self.c.id),
                'building_code': 'RACE', 'status': 'Active'},
                record_id=self.hs.id)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Xray Prep', resp.content.decode())

    def test_edit_code_race_is_form_error(self):
        from unittest import mock
        other = _hs('Whiskey')
        real_clean = HighSchoolCampusForm._post_clean

        def clean_then_race(form):
            out = real_clean(form)
            _link(other, self.a, 'EDR')
            return out
        with mock.patch.object(HighSchoolCampusForm, "_post_clean", clean_then_race):
            resp = self._call(views.highschool_campus_edit, self.staff, post={
                'apply': '1', 'building_code': 'EDR', 'status': 'Active'},
                link_id=self.link_a.id)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Whiskey', resp.content.decode())

    def test_unlinking_host_campus_redirects(self):
        resp = self._call(views.highschool_campus_delete, self.staff,
                          post={'apply': '1'}, link_id=self.link_a.id)
        data = self._json(resp)
        self.assertEqual(data['outcome'], 'redirect')
        self.assertEqual(data['url'], reverse('cis:highschools'))


class EditDeleteTests(_Base):
    def _edit(self, user, link, post=None):
        return self._call(views.highschool_campus_edit, user, post=post,
                          link_id=link.id)

    def _delete(self, user, link, post=None):
        return self._call(views.highschool_campus_delete, user, post=post,
                          link_id=link.id)

    def test_edit_modal_then_apply(self):
        self.assertEqual(
            self._json(self._edit(self.staff, self.link_a, {}))['outcome'], 'modal')
        resp = self._edit(self.staff, self.link_a, {
            'apply': '1', 'building_code': 'A2', 'status': 'Inactive'})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.link_a.refresh_from_db()
        self.assertEqual((self.link_a.building_code, self.link_a.status),
                         ('A2', 'Inactive'))

    def test_edit_duplicate_code_is_form_error(self):
        other = _hs('Yankee')
        _link(other, self.a, 'TAKEN')
        resp = self._edit(self.staff, self.link_a, {
            'apply': '1', 'building_code': 'TAKEN', 'status': 'Active'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Yankee', resp.content.decode())
        self.link_a.refresh_from_db()
        self.assertEqual(self.link_a.building_code, 'AA')

    def test_edit_keeping_own_code_ok(self):
        resp = self._edit(self.staff, self.link_a, {
            'apply': '1', 'building_code': 'AA', 'status': 'Inactive'})
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_delete_modal_then_apply(self):
        self.assertEqual(
            self._json(self._delete(self.staff, self.link_a, {}))['outcome'], 'modal')
        self.assertTrue(HighSchoolCampus.objects.filter(pk=self.link_a.pk).exists())
        resp = self._delete(self.staff, self.link_a, {'apply': '1'})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(HighSchoolCampus.objects.filter(pk=self.link_a.pk).exists())

    def test_other_campus_link_403_on_all(self):
        for post in ({}, {'apply': '1', 'building_code': 'X', 'status': 'Active'}):
            self.assertEqual(self._edit(self.staff, self.link_b, post).status_code, 403)
        for post in ({}, {'apply': '1'}):
            self.assertEqual(self._delete(self.staff, self.link_b, post).status_code, 403)
        self.link_b.refresh_from_db()
        self.assertEqual(self.link_b.building_code, 'BB')

    def test_superuser_may_edit_any(self):
        resp = self._edit(self.su, self.link_b, {
            'apply': '1', 'building_code': 'B2', 'status': 'Active'})
        self.assertEqual(resp.status_code, 200, resp.content)


class FormTests(_Base):
    def test_choices_exclude_non_processable_and_linked(self):
        form = HighSchoolCampusForm(user=self.staff, highschool=self.hs)
        ids = {str(c.pk) for c in form.fields['campus'].queryset}
        self.assertEqual(ids, {str(self.c.id)})

    def test_superuser_choices_exclude_linked_only(self):
        form = HighSchoolCampusForm(user=self.su, highschool=self.hs)
        ids = {c.pk for c in form.fields['campus'].queryset}
        self.assertNotIn(self.a.pk, ids)
        self.assertNotIn(self.b.pk, ids)
        self.assertIn(self.c.pk, ids)
        self.assertEqual(ids, {c.pk for c in get_accessible_campuses(self.su)} - {self.a.pk, self.b.pk})

    def test_urls_resolve(self):
        reverse('cis:highschool_campus_add', args=[self.hs.id])
        reverse('cis:highschool_campus_edit', args=[self.link_a.id])
        reverse('cis:highschool_campus_delete', args=[self.link_a.id])
