"""Menu items carry an optional ``display`` flag.

An item (or sub_menu child) with ``"display": false`` is hidden from the
sidebar, from the dashboard tiles, and from the per-page blurb fields of the
portal-language settings — without losing any blurb text already stored for it.
"""
import json

from django.test import RequestFactory, TestCase

from cis.menu import draw_menu, get_role_menu, is_visible
from cis.models.settings import Setting
from cis.settings.menu import menu as menu_setting

MENU_KEY = 'cis.settings.menu'

HS_MENU = [
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-tachometer-alt',
        'name': 'home',
        'label': 'Home',
        'url': 'highschool_admin:dashboard',
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-user',
        'name': 'students',
        'label': 'Students',
        'url': 'highschool_admin:students',
        'display': False,
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-file',
        'name': 'transcripts',
        'label': 'Transcripts',
        'sub_menu': [
            {'label': 'All', 'name': 'all_transcripts',
             'url': 'highschool_admin:transcripts'},
            {'label': 'Archived', 'name': 'archived_transcripts',
             'url': 'highschool_admin:transcripts', 'display': False},
        ],
    },
]


def seed_menu(items):
    setting, _ = Setting.objects.get_or_create(
        key=MENU_KEY, defaults={'value': {}})
    setting.value = {'highschool_admin_menu': json.dumps(items)}
    setting.save()
    return setting


class IsVisible(TestCase):

    def test_missing_display_key_defaults_to_visible(self):
        self.assertTrue(is_visible({'name': 'home'}))

    def test_false_and_zero_hide(self):
        for value in (False, 0, '0', 'false', 'False'):
            with self.subTest(value=value):
                self.assertFalse(is_visible({'name': 'x', 'display': value}))

    def test_true_and_one_show(self):
        for value in (True, 1, '1', 'true'):
            with self.subTest(value=value):
                self.assertTrue(is_visible({'name': 'x', 'display': value}))


class GetRoleMenu(TestCase):

    def setUp(self):
        seed_menu(HS_MENU)

    def test_hidden_top_level_item_is_dropped(self):
        names = [i['name'] for i in get_role_menu('highschool_admin')]
        self.assertIn('home', names)
        self.assertNotIn('students', names)

    def test_hidden_sub_menu_child_is_dropped(self):
        menu = get_role_menu('highschool_admin')
        transcripts = next(i for i in menu if i['name'] == 'transcripts')
        names = [s['name'] for s in transcripts['sub_menu']]
        self.assertEqual(names, ['all_transcripts'])

    def test_visible_only_false_returns_everything(self):
        menu = get_role_menu('highschool_admin', visible_only=False)
        self.assertEqual([i['name'] for i in menu],
                         ['home', 'students', 'transcripts'])
        transcripts = next(i for i in menu if i['name'] == 'transcripts')
        self.assertEqual(len(transcripts['sub_menu']), 2)

    def test_filtering_does_not_mutate_the_stored_setting(self):
        get_role_menu('highschool_admin')
        stored = json.loads(
            Setting.objects.get(key=MENU_KEY).value['highschool_admin_menu'])
        self.assertEqual(len(stored), 3)
        self.assertEqual(len(stored[2]['sub_menu']), 2)

    def test_missing_or_unparseable_setting_returns_empty_list(self):
        Setting.objects.filter(key=MENU_KEY).delete()
        self.assertEqual(get_role_menu('highschool_admin'), [])
        setting = Setting.objects.create(
            key=MENU_KEY, value={'highschool_admin_menu': 'not json'})
        self.assertEqual(get_role_menu('highschool_admin'), [])


class DrawMenu(TestCase):

    def setUp(self):
        seed_menu(HS_MENU)

    def test_hidden_top_level_item_is_not_rendered(self):
        html = draw_menu(HS_MENU, 'home', '', 'highschool_admin')
        self.assertIn('id_nav_item_home', html)
        self.assertNotIn('id_nav_item_students', html)

    def test_hidden_sub_menu_child_is_not_rendered(self):
        html = draw_menu(HS_MENU, 'transcripts', '', 'highschool_admin')
        self.assertIn('All', html)
        self.assertNotIn('Archived', html)


class PortalBlurbFields(TestCase):
    """The portal-language settings build one textarea per visible menu item."""

    def setUp(self):
        seed_menu(HS_MENU)

    def _form(self):
        from cis.settings.highschool_admin_portal import SettingForm
        return SettingForm()

    def test_hidden_item_has_no_blurb_field(self):
        fields = self._form().fields
        self.assertIn('home_blurb', fields)
        self.assertNotIn('students_blurb', fields)

    def test_hidden_sub_menu_child_has_no_blurb_field(self):
        fields = self._form().fields
        self.assertIn('all_transcripts_blurb', fields)
        self.assertNotIn('archived_transcripts_blurb', fields)

    def test_saving_preserves_blurbs_of_hidden_items(self):
        from cis.settings.highschool_admin_portal import (
            highschool_admin_portal as portal)

        Setting.objects.create(key=portal.key, value={
            'home_blurb': 'old home',
            'students_blurb': 'text for the hidden students page',
        })

        form = portal(request=RequestFactory().get('/'))
        form.cleaned_data = {'home_blurb': 'new home'}
        form.run_record()

        stored = Setting.objects.get(key=portal.key).value
        self.assertEqual(stored['home_blurb'], 'new home')
        self.assertEqual(stored['students_blurb'],
                         'text for the hidden students page')
